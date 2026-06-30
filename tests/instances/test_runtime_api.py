# pylint: disable=import-error, invalid-name, line-too-long, redefined-outer-name, unused-argument
"""Verify that NTC writes are reflected on the Runtime API /functions endpoint (the gateway's
ground truth).

The permission tests in test_instance_permissions.py observe behaviour THROUGH the gateway. These
tests look one layer deeper: after configuring the instance via NTC, they read the SAME endpoint the
gateway reads (Service-CRN + apikey) and assert the entitlements stored there match exactly what was
configured. This pins down the contract (and the response shape) independently of the gateway.
"""

import pytest

from instances.conftest import (
    ALL_CUSTOM,
    ALL_FUNCTIONS,
    NONE_CUSTOM,
    NONE_FUNCTIONS,
    PROVIDER_CUSTOM,
    PROVIDER_FUNCTIONS,
    USER_CUSTOM,
    USER_FUNCTIONS,
    apply_level,
    assert_runtime_matches,
    ensure_account_superset,
    RECONFIG_CRN,
)


@pytest.fixture(autouse=True)
def restore_account(ntc):
    """Restore the account to the superset after each test to avoid cross-test contamination."""
    yield
    ensure_account_superset(ntc)


def test_runtime_reflects_all_level(ntc, runtime, function_title, other_function_title):
    """ALL level: both functions present on the Runtime API with the full permission set + custom."""
    apply_level(ntc, ALL_FUNCTIONS, ALL_CUSTOM)
    assert_runtime_matches(runtime, ALL_FUNCTIONS, ALL_CUSTOM)


def test_runtime_reflects_user_level(ntc, runtime, function_title, other_function_title):
    """USER level: only the test function (trial) with user permissions; sibling absent."""
    apply_level(ntc, USER_FUNCTIONS, USER_CUSTOM)
    assert_runtime_matches(runtime, USER_FUNCTIONS, USER_CUSTOM)


def test_runtime_reflects_provider_level(ntc, runtime, function_title):
    """PROVIDER level: the test function (consumption) with provider permissions; no custom."""
    apply_level(ntc, PROVIDER_FUNCTIONS, PROVIDER_CUSTOM)
    assert_runtime_matches(runtime, PROVIDER_FUNCTIONS, PROVIDER_CUSTOM)


def test_runtime_none_level_is_empty_not_204(ntc, runtime):
    """NONE level (functions=[]) must be the clean 200-empty deny path, NOT a 204 legacy fallback.

    A 204 would make the gateway fall back to legacy Django authorization; configuring functions=[]
    is meant to be an explicit per-function deny that still reports 200 with an empty list.
    """
    apply_level(ntc, NONE_FUNCTIONS, NONE_CUSTOM)
    # Read the Runtime API directly and inspect the raw result (single read, no polling: the
    # advancing PATCH timestamp forces an immediate re-sync, so one read reflects the new state).
    assert_runtime_matches(runtime, NONE_FUNCTIONS, NONE_CUSTOM)
    result = runtime.get_functions(RECONFIG_CRN)
    assert not result.not_configured, (
        "Runtime API returned 204 for functions=[]; expected 200 with an empty list (clean deny). "
        "If this fails, functions=[] is being treated as 'not configured' (legacy fallback)."
    )
    assert result.functions == []
