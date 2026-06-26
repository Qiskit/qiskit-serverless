# pylint: disable=import-error, invalid-name, line-too-long, unused-argument, attribute-defined-outside-init, too-few-public-methods, too-many-arguments, too-many-positional-arguments
"""Instance-based permission tests through the Runtime API /functions endpoint.

These tests verify that each implemented endpoint correctly grants or denies access
depending on the effective permissions of the instance CRN used to authenticate.

Unlike the original suite (which depended on four pre-configured CRNs), this version uses
a SINGLE reconfigurable instance: each test class reconfigures the instance to its level
(NONE / USER / PROVIDER / ALL) right before each test via the NTC APIs, and reuses the
shared assertion battery from permission_checks.py.

Setup (see conftest.py for the full list):
  - GATEWAY_HOST/GATEWAY_TOKEN/GATEWAY_CHANNEL for the serverless client.
  - NTC_API_KEY, NTC_ACCOUNT_ID, TEST_RECONFIG_INSTANCE to configure the instance via NTC.
  - Feature gateway.runtime_instances_api.enabled must be true and the /functions cache disabled.

Effective-permissions model (confirmed in the ntc repo):
  - GET /functions returns the INSTANCE entitlements as-is (it never intersects the account
    at read time).
  - Saving the account narrows the instance entitlements (account->instance sync; only narrows).
  - The broker rejects an instance PATCH that exceeds the account plan.
The account is kept at a superset before each test so the configured level is exactly what
/functions returns. The account->instance propagation itself is covered in
test_instance_propagation.py.
"""

import pytest

from instances.conftest import (
    apply_level,
    ALL_CUSTOM,
    ALL_FUNCTIONS,
    NONE_CUSTOM,
    NONE_FUNCTIONS,
    PROVIDER_CUSTOM,
    PROVIDER_FUNCTIONS,
    USER_CUSTOM,
    USER_FUNCTIONS,
)
from instances.permission_checks import (
    CombinedPermissionChecks,
    CustomFunctionChecks,
    NonePermissionChecks,
    ProviderPermissionChecks,
    UserPermissionChecks,
)


class TestNoPermissionsInstance(NonePermissionChecks):
    """Instance reconfigured to NONE (empty functions list)."""

    @pytest.fixture(autouse=True)
    def _bind(self, ntc, reconfig_client, provider_name, function_title, custom_function_title, seeded_job_id):
        self.provider_name = provider_name
        self.function_title = function_title
        self.custom_function_title = custom_function_title
        self.seeded_job_id = seeded_job_id
        apply_level(ntc, NONE_FUNCTIONS, NONE_CUSTOM)
        self.client = reconfig_client


class TestUserInstance(UserPermissionChecks):
    """Instance reconfigured to USER permissions (business_model TRIAL)."""

    @pytest.fixture(autouse=True)
    def _bind(self, ntc, reconfig_client, provider_name, function_title, seeded_other_function, seeded_job_id):
        self.provider_name = provider_name
        self.function_title = function_title
        self.other_function_title = seeded_other_function
        self.seeded_job_id = seeded_job_id
        apply_level(ntc, USER_FUNCTIONS, USER_CUSTOM)
        self.client = reconfig_client


class TestProviderInstance(ProviderPermissionChecks):
    """Instance reconfigured to PROVIDER permissions."""

    @pytest.fixture(autouse=True)
    def _bind(
        self,
        ntc,
        reconfig_client,
        provider_name,
        function_title,
        custom_function_title,
        seeded_other_function,
        seeded_job_id,
    ):
        self.provider_name = provider_name
        self.function_title = function_title
        self.custom_function_title = custom_function_title
        self.other_function_title = seeded_other_function
        self.seeded_job_id = seeded_job_id
        apply_level(ntc, PROVIDER_FUNCTIONS, PROVIDER_CUSTOM)
        self.client = reconfig_client


class TestCombinedInstance(CombinedPermissionChecks):
    """Instance reconfigured to ALL permissions (business_model CONSUMPTION), two functions."""

    @pytest.fixture(autouse=True)
    def _bind(
        self,
        ntc,
        reconfig_client,
        provider_name,
        function_title,
        custom_function_title,
        seeded_other_function,
        seeded_job_id,
    ):
        self.provider_name = provider_name
        self.function_title = function_title
        self.custom_function_title = custom_function_title
        self.other_function_title = seeded_other_function
        self.seeded_job_id = seeded_job_id
        apply_level(ntc, ALL_FUNCTIONS, ALL_CUSTOM)
        self.client = reconfig_client


class TestCustomFunctionInstance(CustomFunctionChecks):
    """Instance reconfigured to USER permissions (which include function-custom.write/run)."""

    @pytest.fixture(autouse=True)
    def _bind(self, ntc, reconfig_client, custom_function_title):
        self.custom_function_title = custom_function_title
        apply_level(ntc, USER_FUNCTIONS, USER_CUSTOM)
        self.client = reconfig_client
