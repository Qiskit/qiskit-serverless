# pylint: disable=import-error, invalid-name, line-too-long, redefined-outer-name
"""Account -> instance propagation tests (black-box) over a single reconfigurable instance.

Confirmed NTC behaviour (see the ntc repo, apps/api/repositories/account_plans.go):
  - Saving the account runs a synchronous sync that NARROWS each instance's entitlements to
    the intersection with the account, by (provider, name, business_model) key. It only ever
    narrows; it never re-adds.
  - GET /functions returns the instance entitlements as-is (no account intersection at read).
  - The broker rejects an instance PATCH that exceeds the account plan grants.

These tests exercise that semantics end-to-end through the serverless /functions endpoint.
"""

import pytest
from qiskit_serverless.exception import QiskitServerlessException

from instances.conftest import (
    ALL_CUSTOM,
    ALL_FUNCTIONS,
    NARROW_ACCOUNT_FUNCTIONS,
    SUPERSET_CUSTOM,
    apply_level,
    ensure_account_superset,
    RECONFIG_CRN,
    _fn,
)
from instances.ntc_client import NtcApiError
from instances.permission_checks import _assert_404, _function_in_list


@pytest.fixture(autouse=True)
def restore_account(ntc):
    """Restore the account to the superset after each test to avoid cross-test contamination."""
    yield
    ensure_account_superset(ntc)


def test_account_narrows_instance_and_does_not_restore(
    ntc, reconfig_client, provider_name, function_title, seeded_other_function
):
    """The 4-step propagation flow (kept on the NTC 200 path throughout):

    1. account superset + instance ALL           -> function is usable
    2. narrow the ACCOUNT to a sibling only       -> instance narrowed -> function gone
    3. re-add the function to the ACCOUNT         -> NOT restored (sync only narrows)
    4. re-add the function to the INSTANCE        -> usable again

    Step 2 narrows the account to a DIFFERENT function (the sibling is kept) instead of clearing it,
    so the instance keeps a non-empty entitlement set. An empty instance makes the Runtime API
    return 204, which the gateway treats as "not migrated" and falls back to legacy Django
    authorization (the function may stay visible); a non-empty instance stays on the 200 path, where
    the narrow is a clean per-function deny we can observe through /functions.
    """
    sibling_title = seeded_other_function

    # Each visibility change is read back immediately (no polling, no sleep): the account narrow-sync
    # is synchronous and the instance PATCH carries an advancing timestamp that makes the Runtime API
    # re-sync at once, so a single read after each change reflects the new state.

    # 1) account superset + instance ALL -> works
    apply_level(ntc, ALL_FUNCTIONS, ALL_CUSTOM)
    listed = reconfig_client.functions(filter="catalog")
    assert _function_in_list(
        listed, provider_name, function_title
    ), "Step 1: expected the function to be present with account+instance configured"

    # 2) narrow the account to the sibling only -> the sync drops the function from the instance,
    #    but the instance stays non-empty (the sibling remains), so we stay on the 200 path.
    ntc.set_account_entitlements(NARROW_ACCOUNT_FUNCTIONS, SUPERSET_CUSTOM)
    remaining = reconfig_client.functions(filter="catalog")
    assert not _function_in_list(
        remaining, provider_name, function_title
    ), "Step 2: expected the function to disappear after narrowing it out of the account"
    assert _function_in_list(
        remaining, provider_name, sibling_title
    ), "Step 2: the sibling function must remain (proves a per-function narrow, not a 204 wipe)"
    with pytest.raises(QiskitServerlessException) as exc:
        reconfig_client.run(function_title, provider=provider_name)
    _assert_404(exc)

    # 3) re-add the function to the account -> the instance is NOT restored (sync only narrows).
    #    The narrow-sync is synchronous, so once ensure_account_superset returns the (non-)effect on
    #    the instance is already settled and a direct read cannot pass by racing ahead of it.
    ensure_account_superset(ntc)
    assert not _function_in_list(
        reconfig_client.functions(filter="catalog"), provider_name, function_title
    ), "Step 3: re-adding the function to the account must NOT restore the instance"

    # 4) re-add the function to the instance -> usable again
    apply_level(ntc, ALL_FUNCTIONS, ALL_CUSTOM)
    listed = reconfig_client.functions(filter="catalog")
    assert _function_in_list(
        listed, provider_name, function_title
    ), "Step 4: expected the function to be usable again after reconfiguring the instance"


def test_instance_patch_rejected_when_exceeding_account(ntc, function_title):
    """The broker rejects an instance PATCH that asks for more than the account grants.

    The account grants only function.read for the function; requesting function.run on the
    instance must be rejected with a 4xx validation error.
    """
    ntc.set_account_entitlements([_fn(function_title, "trial", ["function.read"])], [])
    with pytest.raises(NtcApiError) as exc:
        ntc.set_instance_entitlements(
            RECONFIG_CRN,
            [_fn(function_title, "trial", ["function.read", "function.run"])],
            [],
        )
    status = exc.value.status
    assert status is not None and 400 <= status < 500, f"Expected a 4xx rejection, got status {status}"
