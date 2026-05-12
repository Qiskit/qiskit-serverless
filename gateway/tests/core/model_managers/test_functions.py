"""Tests for FunctionsQuerySet model manager."""

import pytest
from django.contrib.auth.models import User

from core.domain.authorization.function_access_entry import FunctionAccessEntry
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.domain.business_models import BusinessModel
from core.models import Program, Provider, PLATFORM_PERMISSION_READ
from tests.utils import TestUtils

pytestmark = pytest.mark.django_db


def make_result(provider_name, function_title, permissions):
    entry = FunctionAccessEntry(
        provider_name=provider_name,
        function_title=function_title,
        permissions=permissions,
        business_model=BusinessModel.SUBSIDIZED,
    )
    return FunctionAccessResult(use_legacy_authorization=False, functions=[entry])


@pytest.fixture()
def author():
    return User.objects.create_user(username="author")


@pytest.fixture()
def other_user():
    return User.objects.create_user(username="other")


@pytest.fixture()
def provider():
    return Provider.objects.create(name="my-provider")


class TestWithPermissionRuntimeInstances:
    def test_returns_allowed(self, author, other_user, provider):
        """When accessible_functions provided, returns matched provider functions."""
        provider_function = Program.objects.create(title="my-function", author=author, provider=provider)
        accessible = make_result(provider.name, "my-function", {PLATFORM_PERMISSION_READ})

        result = list(
            Program.objects.with_permission(
                author=other_user,
                accessible_functions=accessible,
                permission=PLATFORM_PERMISSION_READ,
            )
        )

        assert provider_function in result

    def test_excludes_function_not_in_accessible(self, author, other_user, provider):
        """When accessible_functions doesn't include the function, it's excluded."""
        provider_function = Program.objects.create(title="my-function", author=author, provider=provider)
        accessible = make_result(provider.name, "other-function", {PLATFORM_PERMISSION_READ})

        result = list(
            Program.objects.with_permission(
                author=other_user,
                accessible_functions=accessible,
                permission=PLATFORM_PERMISSION_READ,
            )
        )

        assert provider_function not in result

    def test_excludes_function_missing_permission(self, author, other_user, provider):
        """When the function entry lacks the permission, it's excluded."""
        provider_function = Program.objects.create(title="my-function", author=author, provider=provider)
        accessible = make_result(provider.name, provider_function.title, {"other-permission"})

        result = list(
            Program.objects.with_permission(
                author=other_user,
                accessible_functions=accessible,
                permission=PLATFORM_PERMISSION_READ,
            )
        )

        assert provider_function not in result

    def test_own_provider_function_excluded_when_permission_absent(self, author, provider):
        """Provider function authored by the querying user is excluded when permission is absent.

        Regression: Q(author=author) without provider=None would include provider functions
        authored by the user regardless of instance permissions.
        """
        provider_function = Program.objects.create(title="my-provider-fn", author=author, provider=provider)
        # accessible_functions has an entry for the function but with a different permission
        accessible = make_result(provider.name, provider_function.title, {"function.write"})

        result = list(
            Program.objects.with_permission(
                author=author,
                accessible_functions=accessible,
                permission=PLATFORM_PERMISSION_READ,
            )
        )

        assert provider_function not in result

    def test_empty_functions_returns_only_own(self, author, other_user):
        """When accessible_functions has no entries, returns only own functions."""
        user_function = Program.objects.create(title="user-fn", author=author)
        own_function = Program.objects.create(title="my-own", author=other_user)
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        result = list(
            Program.objects.with_permission(
                author=other_user,
                accessible_functions=accessible,
                permission=PLATFORM_PERMISSION_READ,
            )
        )

        assert own_function in result
        assert user_function not in result


class TestWithPermissionDjangoGroups:
    def test_none_accessible_functions_uses_django_groups(self, author, provider):
        """When accessible_functions=None, falls back to Django groups."""
        provider_function = Program.objects.create(title="my-function", author=author, provider=provider)
        user_function = Program.objects.create(title="user-fn", author=author)

        result = list(
            Program.objects.with_permission(
                author=author, legacy_permission_name="view_program", accessible_functions=None
            )
        )

        assert user_function in result
        assert provider_function in result

    def test_legacy_authorization_true_uses_django_groups(self, author, other_user, provider):
        """When use_legacy_authorization=True, falls back to Django groups and filters correctly."""
        provider_function = Program.objects.create(title="my-function", author=author, provider=provider)
        user_function = Program.objects.create(title="user-fn", author=author)
        other_function = Program.objects.create(title="other-fn", author=other_user)
        accessible = FunctionAccessResult(use_legacy_authorization=True)
        result = list(
            Program.objects.with_permission(
                author=author,
                legacy_permission_name="view_program",
                accessible_functions=accessible,
            )
        )

        assert user_function in result
        assert provider_function in result
        assert other_function not in result


class TestGetFunctionByPermissionRuntimeInstances:
    def test_returns_function_when_permitted(self, author, other_user, provider):
        """When function entry has the permission, returns the function."""
        provider_function = Program.objects.create(title="my-function", author=author, provider=provider)
        accessible = make_result(provider.name, provider_function.title, {PLATFORM_PERMISSION_READ})

        result = Program.objects.get_function_by_permission(
            user=other_user,
            function_title="my-function",
            provider_name="my-provider",
            accessible_functions=accessible,
            permission=PLATFORM_PERMISSION_READ,
        )

        assert result == provider_function

    @pytest.mark.parametrize(
        "accessible",
        [
            make_result("my-provider", "other-function", {PLATFORM_PERMISSION_READ}),
            make_result("my-provider", "my-function", {"other-permission"}),
            make_result("other-provider", "my-function", {PLATFORM_PERMISSION_READ}),
        ],
    )
    def test_returns_none_when_not_accessible(self, author, other_user, provider, accessible):
        """Returns None when function, permission, or provider doesn't match accessible_functions."""
        Program.objects.create(title="my-function", author=author, provider=provider)
        result = Program.objects.get_function_by_permission(
            user=other_user,
            function_title="my-function",
            provider_name="my-provider",
            accessible_functions=accessible,
            permission=PLATFORM_PERMISSION_READ,
        )

        assert result is None

    def test_no_provider_returns_own_function(self, author):
        """When provider_name is None, returns user's own function (no permission check)."""
        own_fn = Program.objects.create(title="own-fn", author=author)
        accessible = make_result("x", "y", {PLATFORM_PERMISSION_READ})

        result = Program.objects.get_function_by_permission(
            user=author,
            function_title="own-fn",
            provider_name=None,
            accessible_functions=accessible,
            permission=PLATFORM_PERMISSION_READ,
        )

        assert result == own_fn


class TestGetFunctionByPermissionDjangoGroup:
    def test_none_accessible_functions_uses_django_groups(self, author, other_user, provider):
        """When accessible_functions=None, falls back to Django groups (no group → None)."""
        Program.objects.create(title="my-function", author=author, provider=provider)
        result = Program.objects.get_function_by_permission(
            accessible_functions=None,
            user=other_user,
            legacy_permission_name="view_program",
            function_title="my-function",
            provider_name="my-provider",
        )

        # other_user is not the author and has no group with view_program → None
        assert result is None

    def test_returns_function_when_user_has_group_permission(self, author, other_user, provider):
        """When accessible_functions=None and user is in a group with permission, returns the function."""
        provider_function = Program.objects.create(title="my-function", author=author, provider=provider)
        group = TestUtils.get_or_create_group("provider-access-group", [("view_program", "core", "program")])
        TestUtils.add_user_to_group(other_user, group)
        provider_function.instances.add(group)

        result = Program.objects.get_function_by_permission(
            accessible_functions=None,
            user=other_user,
            function_title="my-function",
            provider_name="my-provider",
            legacy_permission_name="view_program",
        )

        assert result == provider_function
