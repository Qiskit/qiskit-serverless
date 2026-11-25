"""Tests for ProgramAccessPolicies."""

import pytest

from django.contrib.auth.models import User

from api.access_policies.programs import ProgramAccessPolicies
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import (
    PLATFORM_PERMISSION_CUSTOM_WRITE,
    PLATFORM_PERMISSION_READ,
    PLATFORM_PERMISSION_RUN,
    PLATFORM_PERMISSION_USER_FILES_READ,
    PLATFORM_PERMISSION_USER_FILES_WRITE,
    RUN_PROGRAM_PERMISSION,
    Program,
    Provider,
)
from tests.utils import TestUtils, create_function_access_result

pytestmark = pytest.mark.django_db


class TestProviderFunctionChecks:
    @pytest.fixture(name="function")
    def function_fixture(self):
        author = User.objects.create_user(username="fn-author")
        provider = Provider.objects.create(name="fn-provider")
        return Program.objects.create(title="fn-title", author=author, provider=provider)

    @pytest.mark.parametrize(
        "method,permission",
        [
            ("can_read", PLATFORM_PERMISSION_READ),
            ("can_run", PLATFORM_PERMISSION_RUN),
            ("can_read_user_files", PLATFORM_PERMISSION_USER_FILES_READ),
            ("can_write_user_files", PLATFORM_PERMISSION_USER_FILES_WRITE),
        ],
    )
    def test_runtime_instances_grant_access_with_the_matching_permission(self, function, method, permission):
        user = User.objects.create_user(username="fn-user")
        check = getattr(ProgramAccessPolicies, method)

        assert check(user, function, create_function_access_result("fn-provider", "fn-title", {permission}))
        assert not check(user, function, create_function_access_result("fn-provider", "fn-title", {"other"}))

    def test_runtime_instances_give_the_author_no_bypass(self, function):
        accessible = FunctionAccessResult(use_legacy_authorization=False)
        assert ProgramAccessPolicies.can_run(function.author, function, accessible) is False

    def test_legacy_grants_access_through_a_group_of_the_function(self, function):
        user = User.objects.create_user(username="fn-user")
        group = TestUtils.get_or_create_group("fn-group", [(RUN_PROGRAM_PERMISSION, "api", "program")])
        TestUtils.add_user_to_group(user, group)
        function.instances.add(group)
        accessible = FunctionAccessResult(use_legacy_authorization=True)

        assert ProgramAccessPolicies.can_run(user, function, accessible) is True
        assert ProgramAccessPolicies.can_run(User.objects.create_user(username="fn-other"), function, None) is False

    def test_legacy_author_keeps_access(self, function):
        assert ProgramAccessPolicies.can_run(function.author, function, None) is True


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
                ({PLATFORM_PERMISSION_CUSTOM_WRITE}, True),
                ({"other-permission"}, False),
                (set(), False),
            ],
        )
        def test_access_depends_on_custom_create_permission(self, permissions, expected):
            """Access is granted only if custom_function_permissions includes PLATFORM_PERMISSION_CUSTOM_WRITE."""
            user = User.objects.create_user(username="runtime-create")
            accessible = FunctionAccessResult(
                use_legacy_authorization=False,
                custom_function_permissions=permissions,
            )
            assert ProgramAccessPolicies.can_create(user, accessible_functions=accessible) is expected
