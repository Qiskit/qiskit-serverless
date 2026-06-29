# pylint: disable=import-error, invalid-name, line-too-long, redefined-outer-name, too-many-arguments, too-many-positional-arguments
"""Fixtures for instance permission tests.

These tests run against a SINGLE service instance whose entitlements are reconfigured
on the fly through the NTC admin/resource-controller APIs (see ntc_client.py). The
instance is taken to NONE/USER/PROVIDER/ALL states before each test so the same battery
of /functions assertions (permission_checks.py) can be reused.

Required environment variables for the STAGING tests (those that talk to NTC are skipped if any is
missing; the offline client tests in test_ntc_client.py / test_runtime_api_client.py do not use these
and always run):
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

from pytest import exit as pytest_exit, fixture, skip
from qiskit_serverless import QiskitFunction, ServerlessClient
from qiskit_serverless.exception import QiskitServerlessException

from instances.ntc_client import NtcAdminClient, NtcApiError, mask_secret
from instances.runtime_api_client import RuntimeApiClient, RuntimeApiError

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

# The Runtime API /functions endpoint is the gateway's ground truth (see
# gateway/api/clients/function_access_client.py): the gateway reads it with the user's token as
# "apikey" and the instance CRN as "Service-CRN". We query the SAME endpoint directly from the
# tests to observe propagation before the gateway cache and to verify what NTC actually stored.
# RUNTIME_API_BASE_URL defaults to the gateway's own default (the NTC admin host); RUNTIME_API_KEY
# defaults to GATEWAY_TOKEN, which for channel=ibm_quantum_platform IS the IBM Cloud API key the
# gateway forwards to the Runtime API.
RUNTIME_API_BASE_URL = os.environ.get("RUNTIME_API_BASE_URL", NTC_ADMIN_BASE)
RUNTIME_API_KEY = os.environ.get("RUNTIME_API_KEY", GATEWAY_TOKEN)

# The gateway caches the per-CRN /functions entitlements for RUNTIME_API_CACHE_TTL seconds
# (1s on staging; see gateway/api/clients/function_access_client.py). Since every level reuses
# the same CRN + token, the cache key is identical, so a reconfiguration is only visible to the
# next gateway read once that entry expires. Wait a little longer than the TTL after each change.
# (Measured propagation on staging is ~2s, so the default leaves a margin above the gateway TTL.)
CACHE_WAIT_SECONDS = float(os.environ.get("TEST_CACHE_WAIT_SECONDS", "3"))

# On top of the gateway cache, the NTC -> Runtime API propagation is eventually-consistent: right
# after raising the instance to ALL, /functions may not yet grant function.write for a function, so
# a seed upload can 404 ("doesn't exist"). The seed fixtures are session-scoped, so a single such
# failure would poison every dependent test for the whole session. Retry the seed uploads until the
# entitlement propagates (or this timeout elapses).
SEED_UPLOAD_TIMEOUT_SECONDS = float(os.environ.get("TEST_SEED_UPLOAD_TIMEOUT_SECONDS", "60"))

# Same eventual consistency applies to visibility changes in the catalog: after a reconfiguration,
# a function may take a moment to (dis)appear from /functions. A change that ADDS a function (e.g.
# re-adding it to the instance) is the slow case; functions that did not change are already visible.
# A single fixed sleep can lose that race, so the propagation tests poll up to this timeout.
PROPAGATION_TIMEOUT_SECONDS = float(os.environ.get("TEST_PROPAGATION_TIMEOUT_SECONDS", "30"))

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

# Account narrowed to a SIBLING function only (excludes FUNCTION_TITLE but keeps OTHER_FUNCTION_TITLE).
# Used by the propagation test to narrow FUNCTION_TITLE out of the instance while keeping the instance
# non-empty: an empty instance returns 204 (legacy Django fallback, the function may stay visible),
# whereas a non-empty instance stays on the 200 path where the narrow is a clean per-function deny.
NARROW_ACCOUNT_FUNCTIONS = [_fn(OTHER_FUNCTION_TITLE, "consumption", ALL_PERMISSIONS)]


def wait_for_propagation():
    """Sleep long enough for the gateway per-CRN entitlements cache to expire.

    Call this after any NTC reconfiguration that a subsequent gateway read must observe.
    """
    logger.info("apply: waiting %.1fs for the gateway entitlements cache to expire", CACHE_WAIT_SECONDS)
    time.sleep(CACHE_WAIT_SECONDS)


def wait_for_catalog(client, provider_name, title, present, timeout=PROPAGATION_TIMEOUT_SECONDS):
    """Poll the catalog until ``title`` reaches the desired visibility, or the timeout elapses.

    NTC -> Runtime API propagation is eventually-consistent and the gateway caches /functions, so a
    visibility change is not observable immediately after a reconfiguration; a single fixed sleep can
    lose the race (notably when a function is RE-ADDED to the instance). Returns the last catalog
    list either way, so the caller can assert on it and still produce a useful failure message.
    """
    # Imported lazily to avoid a circular import: permission_checks is fixture-agnostic and does not
    # depend on conftest, so importing it here (not at module load) keeps that direction one-way.
    from instances.permission_checks import _function_in_list  # pylint: disable=import-outside-toplevel

    deadline = time.monotonic() + timeout
    attempt = 0
    while True:
        attempt += 1
        functions = client.functions(filter="catalog")
        if _function_in_list(functions, provider_name, title) == present:
            return functions
        if time.monotonic() >= deadline:
            logger.warning(
                "catalog: %s/%s still %s after %.0fs", provider_name, title, "absent" if present else "present", timeout
            )
            return functions
        logger.info(
            "catalog: waiting for %s/%s to become %s (attempt %d), retrying in %.1fs",
            provider_name,
            title,
            "visible" if present else "hidden",
            attempt,
            CACHE_WAIT_SECONDS,
        )
        time.sleep(CACHE_WAIT_SECONDS)


def wait_for_runtime(runtime, title, present, require_permissions=None, timeout=PROPAGATION_TIMEOUT_SECONDS):
    """Poll the Runtime API (the gateway's ground truth) until ``title`` reaches the desired state.

    This reads the SAME endpoint the gateway uses, so it observes propagation before the gateway
    cache. ``present`` is the desired visibility; ``require_permissions`` (optional) is a set/list
    of permissions that must ALL be granted for ``title`` before we consider it ready (used by the
    seeds, which need function.write to exist before uploading). Returns the last RuntimeFunctions
    read either way, so the caller can assert and still get a useful message.
    """
    required = set(require_permissions or [])
    deadline = time.monotonic() + timeout
    attempt = 0
    while True:
        attempt += 1
        result = runtime.get_functions(RECONFIG_CRN)
        has = result.has_function(PROVIDER_NAME, title)
        perms_ok = required.issubset(result.permissions(PROVIDER_NAME, title)) if required else True
        if has == present and perms_ok:
            return result
        if time.monotonic() >= deadline:
            logger.warning(
                "runtime: %s/%s still not in desired state after %.0fs (present=%s perms=%s): %s",
                PROVIDER_NAME,
                title,
                timeout,
                present,
                sorted(required),
                result.summary(),
            )
            return result
        logger.info(
            "runtime: waiting for %s/%s present=%s perms=%s (attempt %d), retrying in %.1fs: %s",
            PROVIDER_NAME,
            title,
            present,
            sorted(required),
            attempt,
            CACHE_WAIT_SECONDS,
            result.summary(),
        )
        time.sleep(CACHE_WAIT_SECONDS)


def _runtime_mismatch(result, expected_functions, expected_custom):
    """Return a human-readable reason the Runtime API result differs from expected, or None if OK."""
    if result.not_configured:
        return f"Runtime API returned 204 (not configured); expected {len(expected_functions)} functions"

    # Key by (provider, name, business_model) so two entries that differ only in business_model are
    # distinct (business_model is compared case-insensitively, as the Runtime API may echo a
    # different case). Folding it into the key also makes the business_model mismatch show up as a
    # key-set difference instead of being silently collapsed onto one (provider, name).
    def _key(f):
        return (f["provider"], f["name"], (f.get("business_model") or "").lower())

    expected_by_key = {_key(f): f for f in expected_functions}
    got_by_key = {_key(f): f for f in result.functions}
    if set(got_by_key) != set(expected_by_key):
        return f"functions mismatch: expected {sorted(expected_by_key)}, got {sorted(got_by_key)}"

    for key, expected in expected_by_key.items():
        got = got_by_key[key]
        if set(got["permissions"]) != set(expected["permissions"]):
            provider, name, _ = key
            return (
                f"{provider}/{name} permissions mismatch: expected {sorted(expected['permissions'])}, "
                f"got {sorted(got['permissions'])}"
            )

    if result.custom_permissions != set(expected_custom or []):
        return (
            f"custom permissions mismatch: expected {sorted(set(expected_custom or []))}, "
            f"got {sorted(result.custom_permissions)}"
        )
    return None


def assert_runtime_matches(runtime, expected_functions, expected_custom, timeout=PROPAGATION_TIMEOUT_SECONDS):
    """Assert the Runtime API exposes exactly ``expected_functions``/``expected_custom`` for the CRN.

    ``expected_functions`` is the same list shape used to configure the instance (``_fn`` entries).
    Permissions are compared as sets; business_model is compared case-insensitively (the Runtime API
    may echo a different case). Polls until the state matches (propagation is eventually-consistent)
    or the timeout elapses, then asserts on the last read.
    """
    deadline = time.monotonic() + timeout
    while True:
        result = runtime.get_functions(RECONFIG_CRN)
        reason = _runtime_mismatch(result, expected_functions, expected_custom)
        if reason is None:
            return result
        if time.monotonic() >= deadline:
            # raise explicitly (not `assert`) so the failure survives `python -O`, where assert is a
            # no-op and the loop would otherwise spin forever.
            raise AssertionError(f"Runtime API {reason} (after polling {timeout:.0f}s); last: {result.summary()}")
        logger.info("runtime: not matching yet (%s), retrying in %.1fs", reason, CACHE_WAIT_SECONDS)
        time.sleep(CACHE_WAIT_SECONDS)


def dump_propagation_state(ntc, runtime):
    """Log the stored instance entitlements (resource-controller) vs the Runtime API view.

    Useful when a seed lags: it shows whether the instance document already has the function while the
    Runtime API has not caught up yet. Returns a one-line summary for inline logging.
    """
    runtime_summary = "<unavailable>"
    stored = "<unavailable>"
    try:
        params = (ntc.get_instance(RECONFIG_CRN).get("parameters") or {}).get("functions")
        stored = [f.get("name") for f in params] if params else params
    except NtcApiError as exc:
        logger.warning("diagnose: could not read instance document: %s", exc)
    try:
        result = runtime.get_functions(RECONFIG_CRN)
        runtime_summary = result.summary()
    except RuntimeApiError as exc:
        logger.warning("diagnose: could not read Runtime API functions: %s", exc)
    logger.info("diagnose: instance stored functions=%s | runtime /functions: %s", stored, runtime_summary)
    return f"stored={stored} runtime={runtime_summary}"


def seed_with_recovery(attempt, what, diagnose=None):
    """Run ``attempt`` (e.g. a seed upload), retrying through NTC -> Runtime API propagation lag.

    The seeds are session-scoped, so a single failed setup would cascade into dozens of failures.
    Retry ``attempt`` until it succeeds or ``SEED_UPLOAD_TIMEOUT_SECONDS`` elapses; on timeout call
    ``pytest.exit`` to abort the whole session instead of running a battery of tests that all depend
    on the missing seed.

    ``diagnose`` is an optional callable returning a short string (e.g. the Runtime API state) that
    is logged on each failure to make the cause visible.
    """
    deadline = time.monotonic() + SEED_UPLOAD_TIMEOUT_SECONDS
    attempts = 0
    while True:
        try:
            return attempt()
        except QiskitServerlessException as exc:
            attempts += 1
            ground_truth = f" | runtime: {diagnose()}" if diagnose else ""
            if time.monotonic() >= deadline:
                logger.error(
                    "seed: %s never succeeded after %.0fs; aborting the session.%s",
                    what,
                    SEED_UPLOAD_TIMEOUT_SECONDS,
                    ground_truth,
                )
                pytest_exit(
                    f"Seed setup for {what} failed: not ready within {SEED_UPLOAD_TIMEOUT_SECONDS:.0f}s. "
                    f"Last error: {exc}",
                    returncode=1,
                )
            logger.info(
                "seed: %s not ready (attempt %d), retrying in %.1fs: %s%s",
                what,
                attempts,
                CACHE_WAIT_SECONDS,
                exc,
                ground_truth,
            )
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


@fixture(scope="session")
def runtime():
    """Read-only client for the Runtime API /functions endpoint (the gateway's ground truth).

    Lets the tests observe what NTC actually propagated (before the gateway cache) and verify the
    entitlement content. Uses RUNTIME_API_KEY (defaults to GATEWAY_TOKEN), the token the gateway
    forwards to the Runtime API for channel=ibm_quantum_platform.
    """
    logger.info(
        "RuntimeApiClient: base=%s key=%s crn=%s",
        RUNTIME_API_BASE_URL,
        mask_secret(RUNTIME_API_KEY),
        RECONFIG_CRN,
    )
    return RuntimeApiClient(RUNTIME_API_BASE_URL, RUNTIME_API_KEY)


# --- seeds (run once, with the instance temporarily at ALL) -----------------------------


def _seed_provider_function(ntc, runtime, reconfig_client, provider_name, title, working_dir, body):
    """Upload a provider function as a seed, made resilient to NTC -> Runtime API propagation lag.

    Puts the instance at ALL, waits on the Runtime API ground truth until function.write is actually
    granted for ``title``, then uploads with ``seed_with_recovery`` so a transient lag retries (and
    ultimately aborts the session instead of cascading). Returns nothing; callers use the uploaded
    function afterwards.
    """
    (working_dir / "main.py").write_text(body)
    fn = QiskitFunction(title=title, provider=provider_name, entrypoint="main.py", working_dir=str(working_dir))

    apply_level(ntc, ALL_FUNCTIONS, ALL_CUSTOM)
    # Ground truth: wait until the Runtime API grants function.write before even attempting to upload.
    wait_for_runtime(runtime, title, present=True, require_permissions=["function.write"])
    seed_with_recovery(
        attempt=lambda: reconfig_client.upload(fn),
        what=f"{provider_name}/{title}",
        diagnose=lambda: dump_propagation_state(ntc, runtime),
    )


@fixture(scope="session")
def seeded_job_id(ntc, runtime, reconfig_client, provider_name, function_title, tmp_path_factory):
    """Ensure a known job exists for the test function.

    Puts the instance at ALL, uploads the function and runs a job. The job belongs to the
    function/author, so it persists even after the instance is later degraded to a lower level.
    """
    _seed_provider_function(
        ntc,
        runtime,
        reconfig_client,
        provider_name,
        function_title,
        tmp_path_factory.mktemp("job_seed"),
        'print("seeded job")\n',
    )
    job = reconfig_client.run(function_title, provider=provider_name)
    return job.job_id


@fixture(scope="session")
def seeded_other_function(ntc, runtime, reconfig_client, provider_name, other_function_title, tmp_path_factory):
    """Create other_function_title in the DB (instance temporarily at ALL).

    This makes isolation tests meaningful: the function exists in the DB but lower levels
    do not list it because it is not in their entitlements.
    """
    _seed_provider_function(
        ntc,
        runtime,
        reconfig_client,
        provider_name,
        other_function_title,
        tmp_path_factory.mktemp("other_fn_seed"),
        'print("other function")\n',
    )
    return other_function_title


@fixture(scope="session")
def seeded_custom_function(ntc, runtime, reconfig_client, custom_function_title, tmp_path_factory):
    """Upload a custom (serverless) function so run/list tests have something to reference."""
    tmp = tmp_path_factory.mktemp("custom_fn_seed")
    (tmp / "main.py").write_text('print("custom function")\n')
    fn = QiskitFunction(title=custom_function_title, entrypoint="main.py", working_dir=str(tmp))

    apply_level(ntc, ALL_FUNCTIONS, ALL_CUSTOM)
    # Custom functions need function-custom.write on the instance, exposed under custom_functions.
    deadline = time.monotonic() + PROPAGATION_TIMEOUT_SECONDS
    while "function-custom.write" not in runtime.get_functions(RECONFIG_CRN).custom_permissions:
        if time.monotonic() >= deadline:
            logger.warning("runtime: function-custom.write still not granted after %.0fs", PROPAGATION_TIMEOUT_SECONDS)
            break
        time.sleep(CACHE_WAIT_SECONDS)
    seed_with_recovery(
        attempt=lambda: reconfig_client.upload(fn),
        what=custom_function_title,
        diagnose=lambda: dump_propagation_state(ntc, runtime),
    )
    return custom_function_title
