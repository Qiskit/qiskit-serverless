# pylint: disable=import-error, invalid-name, line-too-long, redefined-outer-name
"""Fixtures for instance permission tests.

These tests run against a SINGLE service instance whose entitlements are reconfigured
on the fly through the NTC admin/resource-controller APIs (see ntc_client.py). The
instance is taken to NONE/USER/PROVIDER/ALL states before each test so the same battery
of /functions assertions (permission_checks.py) can be reused.

Required environment variables (the whole module is skipped if any is missing):
  - NTC_API_KEY            API key for the NTC account admin API ("apikey" scheme).
  - NTC_ACCOUNT_ID         account id (without the "a/" prefix)
  - TEST_RECONFIG_INSTANCE CRN of the instance to reconfigure

Optional:
  - NTC_RC_API_KEY         API key for the resource-controller (instance) path; exchanged for an
                           IAM Bearer. Defaults to NTC_API_KEY when not set. Use this when the
                           instance lives in a different IBM Cloud account than the admin key.
  - NTC_ADMIN_BASE         default https://quantum.test.cloud.ibm.com
  - NTC_RC_BASE            default https://resource-controller.test.cloud.ibm.com
  - NTC_IAM_BASE           default https://iam.test.cloud.ibm.com
  - NTC_SUBSCRIPTION_NAME  account plan subscription_name to edit (default "flex")
  - GATEWAY_HOST / GATEWAY_TOKEN / GATEWAY_CHANNEL  serverless client config
  - TEST_PROVIDER_NAME / TEST_FUNCTION_TITLE / TEST_OTHER_FUNCTION_TITLE / TEST_CUSTOM_FUNCTION_TITLE
"""

import logging
import os
import time

from pytest import fixture, skip
from qiskit_serverless import QiskitFunction, ServerlessClient

from instances.ntc_client import NtcAdminClient, mask_secret

logger = logging.getLogger("instances.conftest")

GATEWAY_HOST = os.environ.get("GATEWAY_HOST", "http://localhost:8000")
GATEWAY_TOKEN = os.environ.get("GATEWAY_TOKEN", "awesome_token")
GATEWAY_CHANNEL = os.environ.get("GATEWAY_CHANNEL", "ibm_quantum_platform")

PROVIDER_NAME = os.environ.get("TEST_PROVIDER_NAME", "ibm-dev")
FUNCTION_TITLE = os.environ.get("TEST_FUNCTION_TITLE", "instances1-test")
OTHER_FUNCTION_TITLE = os.environ.get("TEST_OTHER_FUNCTION_TITLE", "instances2-test")
CUSTOM_FUNCTION_TITLE = os.environ.get("TEST_CUSTOM_FUNCTION_TITLE", "my-custom-func")

NTC_API_KEY = os.environ.get("NTC_API_KEY")
NTC_RC_API_KEY = os.environ.get("NTC_RC_API_KEY")
NTC_ACCOUNT_ID = os.environ.get("NTC_ACCOUNT_ID")
RECONFIG_CRN = os.environ.get("TEST_RECONFIG_INSTANCE")
NTC_ADMIN_BASE = os.environ.get("NTC_ADMIN_BASE", "https://quantum.test.cloud.ibm.com")
NTC_RC_BASE = os.environ.get("NTC_RC_BASE", "https://resource-controller.test.cloud.ibm.com")
NTC_IAM_BASE = os.environ.get("NTC_IAM_BASE", "https://iam.test.cloud.ibm.com")
NTC_SUBSCRIPTION_NAME = os.environ.get("NTC_SUBSCRIPTION_NAME", "flex")

# The gateway caches the per-CRN /functions entitlements for RUNTIME_API_CACHE_TTL seconds
# (1s on staging; see gateway/api/clients/function_access_client.py). Since every level reuses
# the same CRN + token, the cache key is identical, so a reconfiguration is only visible to the
# next gateway read once that entry expires. Wait a little longer than the TTL after each change.
CACHE_WAIT_SECONDS = float(os.environ.get("TEST_CACHE_WAIT_SECONDS", "2"))

# --- permission sets -------------------------------------------------------------------

USER_PERMISSIONS = ["function.read", "function.run", "function-files.read", "function-files.write"]
PROVIDER_PERMISSIONS = [
    "function.write",
    "function-job.read",
    "function-provider-logs.read",
    "function-provider-files.read",
    "function-provider-files.write",
]
ALL_PERMISSIONS = [
    "function.read",
    "function.run",
    "function-files.read",
    "function-files.write",
    "function.write",
    "function-job.read",
    "function-provider-logs.read",
    "function-provider-files.read",
    "function-provider-files.write",
]
CUSTOM_PERMISSIONS = ["function-custom.write", "function-custom.run"]


def _fn(name, business_model, permissions):
    """Build a function entitlement entry."""
    return {
        "name": name,
        "provider": PROVIDER_NAME,
        "business_model": business_model,
        "permissions": list(permissions),
    }


# Instance entitlements per level. business_model must match the values the reused
# checks expect: TRIAL for user, CONSUMPTION for combined.
NONE_FUNCTIONS = []
NONE_CUSTOM = []

USER_FUNCTIONS = [_fn(FUNCTION_TITLE, "trial", USER_PERMISSIONS)]
USER_CUSTOM = CUSTOM_PERMISSIONS

PROVIDER_FUNCTIONS = [_fn(FUNCTION_TITLE, "consumption", PROVIDER_PERMISSIONS)]
PROVIDER_CUSTOM = []

ALL_FUNCTIONS = [
    _fn(FUNCTION_TITLE, "consumption", ALL_PERMISSIONS),
    _fn(OTHER_FUNCTION_TITLE, "consumption", ALL_PERMISSIONS),
]
ALL_CUSTOM = CUSTOM_PERMISSIONS

# Account superset: must grant, by (provider, name, business_model) key, a superset of
# every instance level so the broker accepts the instance PATCH (validateFunctions) and
# the account->instance sync never narrows the configured level.
SUPERSET_FUNCTIONS = [
    _fn(FUNCTION_TITLE, "trial", ALL_PERMISSIONS),
    _fn(FUNCTION_TITLE, "consumption", ALL_PERMISSIONS),
    _fn(OTHER_FUNCTION_TITLE, "consumption", ALL_PERMISSIONS),
]
SUPERSET_CUSTOM = CUSTOM_PERMISSIONS


def wait_for_propagation():
    """Sleep long enough for the gateway per-CRN entitlements cache to expire.

    Call this after any NTC reconfiguration that a subsequent gateway read must observe.
    """
    logger.info("apply: waiting %.1fs for the gateway entitlements cache to expire", CACHE_WAIT_SECONDS)
    time.sleep(CACHE_WAIT_SECONDS)


def ensure_account_superset(ntc):
    """Set the account plan to the superset so every instance PATCH is accepted."""
    logger.info("apply: account superset -> functions=%d custom=%d", len(SUPERSET_FUNCTIONS), len(SUPERSET_CUSTOM))
    ntc.set_account_entitlements(SUPERSET_FUNCTIONS, SUPERSET_CUSTOM)


def apply_level(ntc, functions, custom_permissions):
    """Put the reconfigurable instance into the given level (account stays at superset).

    Waits for the gateway entitlements cache to expire so the next gateway read sees this level.
    """
    logger.info(
        "apply: level on instance %s -> functions=%d custom=%s",
        RECONFIG_CRN,
        len(functions),
        list(custom_permissions) if custom_permissions else "<clear>",
    )
    ensure_account_superset(ntc)
    ntc.set_instance_entitlements(RECONFIG_CRN, functions, custom_permissions)
    wait_for_propagation()


# --- shared metadata fixtures ----------------------------------------------------------


@fixture(scope="session")
def provider_name():
    """Provider name of the test function."""
    return PROVIDER_NAME


@fixture(scope="session")
def function_title():
    """Title of the test function."""
    return FUNCTION_TITLE


@fixture(scope="session")
def custom_function_title():
    """Title of the custom (serverless) function used to test function-custom.* permissions."""
    return CUSTOM_FUNCTION_TITLE


@fixture(scope="session")
def other_function_title():
    """Title of a second function that exists in the DB but is NOT in every level's entitlements."""
    return OTHER_FUNCTION_TITLE


# --- NTC client and serverless client --------------------------------------------------


@fixture(scope="session")
def ntc():
    """NTC admin client. Skips the whole module if NTC credentials are not configured."""
    if not (NTC_API_KEY and NTC_ACCOUNT_ID and RECONFIG_CRN):
        skip("NTC_API_KEY, NTC_ACCOUNT_ID and TEST_RECONFIG_INSTANCE are required for reconfigurable instance tests")
    return NtcAdminClient(
        account_id=NTC_ACCOUNT_ID,
        api_key=NTC_API_KEY,
        rc_api_key=NTC_RC_API_KEY,
        admin_base=NTC_ADMIN_BASE,
        rc_base=NTC_RC_BASE,
        iam_base=NTC_IAM_BASE,
        subscription_name=NTC_SUBSCRIPTION_NAME,
    )


@fixture(scope="session")
def reconfig_client():
    """ServerlessClient bound to the reconfigurable instance CRN.

    The same client object is reused at every level; only the server-side entitlements
    change (via apply_level), so the client does not encode the permission level.
    """
    logger.info(
        "ServerlessClient: host=%s channel=%s instance=%s token=%s",
        GATEWAY_HOST,
        GATEWAY_CHANNEL,
        RECONFIG_CRN,
        mask_secret(GATEWAY_TOKEN),
    )
    return ServerlessClient(
        token=GATEWAY_TOKEN,
        host=GATEWAY_HOST,
        instance=RECONFIG_CRN,
        channel=GATEWAY_CHANNEL,
    )


# --- seeds (run once, with the instance temporarily at ALL) -----------------------------


@fixture(scope="session")
def seeded_job_id(ntc, reconfig_client, provider_name, function_title, tmp_path_factory):
    """Ensure a known job exists for the test function.

    Puts the instance at ALL, uploads the function and runs a job. The job belongs to the
    function/author, so it persists even after the instance is later degraded to a lower level.
    """
    apply_level(ntc, ALL_FUNCTIONS, ALL_CUSTOM)
    tmp = tmp_path_factory.mktemp("job_seed")
    (tmp / "main.py").write_text('print("seeded job")\n')
    fn = QiskitFunction(
        title=function_title,
        provider=provider_name,
        entrypoint="main.py",
        working_dir=str(tmp),
    )
    reconfig_client.upload(fn)
    job = reconfig_client.run(function_title, provider=provider_name)
    return job.job_id


@fixture(scope="session")
def seeded_other_function(ntc, reconfig_client, provider_name, other_function_title, tmp_path_factory):
    """Create other_function_title in the DB (instance temporarily at ALL).

    This makes isolation tests meaningful: the function exists in the DB but lower levels
    do not list it because it is not in their entitlements.
    """
    apply_level(ntc, ALL_FUNCTIONS, ALL_CUSTOM)
    tmp = tmp_path_factory.mktemp("other_fn_seed")
    (tmp / "main.py").write_text('print("other function")\n')
    fn = QiskitFunction(
        title=other_function_title,
        provider=provider_name,
        entrypoint="main.py",
        working_dir=str(tmp),
    )
    reconfig_client.upload(fn)
    return other_function_title


@fixture(scope="session")
def seeded_custom_function(ntc, reconfig_client, custom_function_title, tmp_path_factory):
    """Upload a custom (serverless) function so run/list tests have something to reference."""
    apply_level(ntc, ALL_FUNCTIONS, ALL_CUSTOM)
    tmp = tmp_path_factory.mktemp("custom_fn_seed")
    (tmp / "main.py").write_text('print("custom function")\n')
    fn = QiskitFunction(
        title=custom_function_title,
        entrypoint="main.py",
        working_dir=str(tmp),
    )
    reconfig_client.upload(fn)
    return custom_function_title
