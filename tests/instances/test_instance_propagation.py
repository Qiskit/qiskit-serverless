# pylint: disable=import-error, invalid-name, line-too-long, redefined-outer-name
"""Account -> instance propagation tests (black-box) over a single reconfigurable instance.

Confirmed NTC behaviour (see the ntc repo, apps/api/repositories/account_plans.go):
  - Saving the account NARROWS each instance's effective entitlements to the intersection with the
    account, by (provider, name, business_model) key. It only ever narrows; it never re-adds. The
    narrow propagates to the Runtime API asynchronously, so step 2 below polls until it lands.
  - GET /functions returns the effective entitlements as-is (no account intersection at read), which
    is why re-widening the account (step 3) does not restore a previously narrowed function.
  - The broker rejects an instance PATCH that exceeds the account plan grants.

These tests exercise that semantics end-to-end through the serverless /functions endpoint.
"""

import time

import pytest
from qiskit_serverless.exception import QiskitServerlessException

from instances.conftest import (
    ALL_CUSTOM,
    ALL_FUNCTIONS,
    NARROW_ACCOUNT_FUNCTIONS,
    SUPERSET_CUSTOM,
    function_entitlement,
)
from instances.ntc_client import NtcApiError
from instances.permission_checks import _assert_404, contains_function


def _poll_functions(client, predicate, timeout=15, interval=0.5):
    """Re-read /functions until predicate(list) holds or timeout elapses; return the last list read."""
    deadline = time.monotonic() + timeout
    listed = client.functions(filter="catalog")
    while not predicate(listed) and time.monotonic() < deadline:
        time.sleep(interval)
        listed = client.functions(filter="catalog")
    return listed


@pytest.fixture(autouse=True)
def restore_account(instance):
    """Restore the account to the superset after each test to avoid cross-test contamination."""
    yield
    instance.reset_account_with_all_functions()


def test_account_narrows_instance_and_does_not_restore(
    instance, serverless_client, provider_name, function_title, populated_other_function
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
    sibling_title = populated_other_function

    # Instance PATCHes carry an advancing timestamp, so those transitions (steps 1 and 4) are read back
    # immediately. The account narrow-sync (step 2) instead propagates to the Runtime API
    # asynchronously, so that one read is polled until it lands.

    # 1) account superset + instance ALL -> works (two writes: account, then instance)
    instance.reset_account_with_all_functions()
    instance.set_entitlements(ALL_FUNCTIONS, ALL_CUSTOM)
    listed = serverless_client.functions(filter="catalog")
    assert contains_function(
        listed, provider_name, function_title
    ), "Step 1: expected the function to be present with account+instance configured"

    # 2) narrow the account to the sibling only -> the sync drops the function from the instance,
    #    but the instance stays non-empty (the sibling remains), so we stay on the 200 path.
    #    The account->Runtime sync is asynchronous, so poll until the function disappears.
    instance.set_account_entitlements(NARROW_ACCOUNT_FUNCTIONS, SUPERSET_CUSTOM)
    remaining = _poll_functions(
        serverless_client, lambda fns: not contains_function(fns, provider_name, function_title)
    )
    assert not contains_function(
        remaining, provider_name, function_title
    ), "Step 2: expected the function to disappear after narrowing it out of the account"
    assert contains_function(
        remaining, provider_name, sibling_title
    ), "Step 2: the sibling function must remain (proves a per-function narrow, not a 204 wipe)"
    with pytest.raises(QiskitServerlessException) as exc:
        serverless_client.run(function_title, provider=provider_name)
    _assert_404(exc)

    # 3) re-add the function to the account -> the instance is NOT restored (sync only narrows).
    #    The effective Runtime view is already {sibling}; re-widening the account can only narrow it
    #    further, never re-add, so a direct read here is stable and cannot race into a false pass.
    instance.reset_account_with_all_functions()
    assert not contains_function(
        serverless_client.functions(filter="catalog"), provider_name, function_title
    ), "Step 3: re-adding the function to the account must NOT restore the instance"

    # 4) re-add the function to the instance -> usable again (the account is already wide from step 3,
    #    so this is a single instance write).
    instance.set_entitlements(ALL_FUNCTIONS, ALL_CUSTOM)
    listed = serverless_client.functions(filter="catalog")
    assert contains_function(
        listed, provider_name, function_title
    ), "Step 4: expected the function to be usable again after reconfiguring the instance"


def test_instance_patch_rejected_when_exceeding_account(instance, function_title):
    """The broker rejects an instance PATCH that asks for more than the account grants.

    The account grants only function.read for the function; requesting function.run on the
    instance must be rejected with a 4xx validation error. The account is set narrow on purpose
    (no reset_account_with_all_functions) so the broker has something to reject.
    """
    instance.set_account_entitlements([function_entitlement(function_title, "trial", ["function.read"])], [])
    with pytest.raises(NtcApiError) as exc:
        instance.set_entitlements(
            [function_entitlement(function_title, "trial", ["function.read", "function.run"])],
            [],
        )
    status = exc.value.status
    assert status is not None and 400 <= status < 500, f"Expected a 4xx rejection, got status {status}"
