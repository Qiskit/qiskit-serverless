"""Tests for ProgramAccessPolicies."""

import pytest

from django.contrib.auth.models import User

from api.access_policies.programs import ProgramAccessPolicies
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import PLATFORM_PERMISSION_CUSTOM_CREATE

pytestmark = pytest.mark.django_db


class TestCanCreate:
    class TestLegacyGroups:
        def test_true_when_accessible_functions_is_none(self):
            """Without runtime instances, custom function creation is always allowed."""
            user = User.objects.create_user(username="legacy-none")
            assert ProgramAccessPolicies.can_create(user) is True

        def test_true_when_use_legacy_authorization(self):
            """Falls back to allow-all when use_legacy_authorization=True."""
            user = User.objects.create_user(username="legacy-true")
            accessible = FunctionAccessResult(use_legacy_authorization=True)
            assert ProgramAccessPolicies.can_create(user, accessible_functions=accessible) is True

    class TestRuntimeInstances:
        @pytest.mark.parametrize(
            "permissions,expected",
            [
                ({PLATFORM_PERMISSION_CUSTOM_CREATE}, True),
                ({"other-permission"}, False),
                (set(), False),
            ],
        )
        def test_access_depends_on_custom_create_permission(self, permissions, expected):
            """Access is granted only if custom_function_permissions includes PLATFORM_PERMISSION_CUSTOM_CREATE."""
            user = User.objects.create_user(username="runtime-create")
            accessible = FunctionAccessResult(
                use_legacy_authorization=False,
                custom_function_permissions=permissions,
            )
            assert ProgramAccessPolicies.can_create(user, accessible_functions=accessible) is expected
