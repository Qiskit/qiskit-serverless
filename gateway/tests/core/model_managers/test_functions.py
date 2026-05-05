"""Tests for FunctionsQuerySet model manager."""

# pylint: disable=unused-argument
import pytest
from django.contrib.auth.models import User

from core.domain.authorization.function_access_entry import FunctionAccessEntry
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.domain.business_models import BusinessModel
from core.models import Program, Provider, Job, PLATFORM_PERMISSION_RUN, PLATFORM_PERMISSION_READ

pytestmark = pytest.mark.django_db

VIEW_PERMISSION = PLATFORM_PERMISSION_READ


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


@pytest.fixture()
def provider_function(provider, author):
    return Program.objects.create(title="my-function", author=author, provider=provider)


@pytest.fixture()
def user_function(author):
    return Program.objects.create(title="user-fn", author=author)


class TestWithPermissionRuntimeInstances:
    def test_returns_own_and_permitted(self, author, other_user, provider, provider_function, user_function):
        """When accessible_functions provided, returns own functions + matched provider functions."""
        accessible = make_result("my-provider", "my-function", {VIEW_PERMISSION})

        result = list(
            Program.objects.with_permission(
                author=other_user,
                legacy_permission_name="view_program",
                accessible_functions=accessible,
                permission=VIEW_PERMISSION,
            )
        )

        assert provider_function in result

    def test_excludes_function_not_in_accessible(self, author, other_user, provider, provider_function):
        """When accessible_functions doesn't include the function, it's excluded."""
        accessible = make_result("my-provider", "other-function", {VIEW_PERMISSION})

        result = list(
            Program.objects.with_permission(
                author=other_user,
                legacy_permission_name="view_program",
                accessible_functions=accessible,
                permission=VIEW_PERMISSION,
            )
        )

        assert provider_function not in result

    def test_excludes_function_missing_permission(self, author, other_user, provider, provider_function):
        """When the function entry lacks the permission, it's excluded."""
        accessible = make_result("my-provider", "my-function", {"other-permission"})

        result = list(
            Program.objects.with_permission(
                author=other_user,
                legacy_permission_name="view_program",
                accessible_functions=accessible,
                permission=VIEW_PERMISSION,
            )
        )

        assert provider_function not in result

    def test_empty_functions_returns_only_own(self, other_user, user_function):
        """When accessible_functions has no entries, returns only own functions."""
        own_function = Program.objects.create(title="my-own", author=other_user)
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        result = list(
            Program.objects.with_permission(
                author=other_user,
                legacy_permission_name="view_program",
                accessible_functions=accessible,
                permission=VIEW_PERMISSION,
            )
        )

        assert own_function in result
        assert user_function not in result


class TestWithPermissionFallback:
    def test_none_accessible_functions_uses_django_groups(self, author, provider_function, user_function):
        """When accessible_functions=None, falls back to Django groups."""
        result = list(
            Program.objects.with_permission(
                author=author,
                legacy_permission_name="view_program",
            )
        )

        # author owns user_function and provider_function
        assert user_function in result
        assert provider_function in result

    def test_legacy_authorization_true_uses_django_groups(self, author, provider_function, user_function):
        """When use_legacy_authorization=True, falls back to Django groups."""
        accessible = FunctionAccessResult(use_legacy_authorization=True)
        result = list(
            Program.objects.with_permission(
                author=author,
                legacy_permission_name="view_program",
                accessible_functions=accessible,
                permission=VIEW_PERMISSION,
            )
        )

        assert user_function in result
        assert provider_function in result


class TestGetFunctionByPermissionRuntimeInstances:
    def test_returns_function_when_permitted(self, author, other_user, provider, provider_function):
        """When function entry has the permission, returns the function."""
        accessible = make_result("my-provider", "my-function", {VIEW_PERMISSION})

        result = Program.objects.get_function_by_permission(
            user=other_user,
            legacy_permission_name="view_program",
            function_title="my-function",
            provider_name="my-provider",
            accessible_functions=accessible,
            permission=VIEW_PERMISSION,
        )

        assert result == provider_function

    def test_returns_none_when_function_not_in_accessible(self, author, other_user, provider, provider_function):
        """When function is not in accessible_functions, returns None."""
        accessible = make_result("my-provider", "other-function", {VIEW_PERMISSION})

        result = Program.objects.get_function_by_permission(
            user=other_user,
            legacy_permission_name="view_program",
            function_title="my-function",
            provider_name="my-provider",
            accessible_functions=accessible,
            permission=VIEW_PERMISSION,
        )

        assert result is None

    def test_returns_none_when_permission_missing(self, author, other_user, provider, provider_function):
        """When entry exists but lacks the permission, returns None."""
        accessible = make_result("my-provider", "my-function", {"other-permission"})

        result = Program.objects.get_function_by_permission(
            user=other_user,
            legacy_permission_name="view_program",
            function_title="my-function",
            provider_name="my-provider",
            accessible_functions=accessible,
            permission=VIEW_PERMISSION,
        )

        assert result is None

    def test_returns_none_when_provider_not_in_accessible(self, author, other_user, provider, provider_function):
        """When provider is not in accessible_functions, returns None."""
        accessible = make_result("other-provider", "my-function", {VIEW_PERMISSION})

        result = Program.objects.get_function_by_permission(
            user=other_user,
            legacy_permission_name="view_program",
            function_title="my-function",
            provider_name="my-provider",
            accessible_functions=accessible,
            permission=VIEW_PERMISSION,
        )

        assert result is None

    def test_no_provider_returns_own_function(self, author):
        """When provider_name is None, returns user's own function (no permission check)."""
        own_fn = Program.objects.create(title="own-fn", author=author)
        accessible = make_result("x", "y", {VIEW_PERMISSION})

        result = Program.objects.get_function_by_permission(
            user=author,
            legacy_permission_name="view_program",
            function_title="own-fn",
            provider_name=None,
            accessible_functions=accessible,
            permission=VIEW_PERMISSION,
        )

        assert result == own_fn


class TestGetFunctionByPermissionFallback:
    def test_none_accessible_functions_uses_django_groups(self, author, other_user, provider, provider_function):
        """When accessible_functions=None, falls back to Django groups (no group → None)."""
        result = Program.objects.get_function_by_permission(
            user=other_user,
            legacy_permission_name="view_program",
            function_title="my-function",
            provider_name="my-provider",
        )

        # other_user is not the author and has no group with view_program → None
        assert result is None
