"""Tests for FunctionsQuerySet model manager."""

# pylint: disable=unused-argument
import pytest
from django.contrib.auth.models import User

from api.domain.authorization.function_access_entry import FunctionAccessEntry
from api.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Program, Provider, Job, PLATFORM_PERMISSION_READ, PLATFORM_PERMISSION_RUN

pytestmark = pytest.mark.django_db


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


def _entry(provider_name, function_title, permissions, business_model=Job.BUSINESS_MODEL_SUBSIDIZED):
    return FunctionAccessEntry(
        provider_name=provider_name,
        function_title=function_title,
        permissions=permissions,
        business_model=business_model,
    )


class TestWithPermissionRuntimeApiClient:
    def test_returns_own_and_permitted(self, author, other_user, provider, provider_function, user_function):
        """When has_response=True, returns own functions + permitted provider functions."""
        entry = _entry("my-provider", "my-function", {PLATFORM_PERMISSION_READ})
        accessible = FunctionAccessResult(has_response=True, functions=[entry])

        result = list(
            Program.objects.with_permission(
                author=other_user,
                legacy_permission_name="view_program",
                accessible_functions=accessible,
                permission=PLATFORM_PERMISSION_READ,
            )
        )

        assert provider_function in result

    def test_excludes_function_without_permission(self, author, other_user, provider, provider_function):
        """When has_response=True and no matching permission, provider function not returned."""
        entry = _entry("my-provider", "my-function", {PLATFORM_PERMISSION_RUN})
        accessible = FunctionAccessResult(has_response=True, functions=[entry])

        result = list(
            Program.objects.with_permission(
                author=other_user,
                legacy_permission_name="view_program",
                accessible_functions=accessible,
                permission=PLATFORM_PERMISSION_READ,
            )
        )

        assert provider_function not in result

    def test_no_entries_returns_only_own(self, author, other_user, user_function):
        """When has_response=True but no entries, returns only own functions."""
        accessible = FunctionAccessResult(has_response=True, functions=[])

        own_function = Program.objects.create(title="my-own", author=other_user)
        result = list(
            Program.objects.with_permission(
                author=other_user,
                legacy_permission_name="view_program",
                accessible_functions=accessible,
                permission=PLATFORM_PERMISSION_READ,
            )
        )

        assert own_function in result
        assert user_function not in result


class TestWithPermissionFallback:
    def test_has_response_false(self, author, provider_function, user_function):
        """When has_response=False, falls back to Django groups (no extra functions)."""
        accessible = FunctionAccessResult(has_response=False)

        result = list(
            Program.objects.with_permission(
                author=author,
                legacy_permission_name="view_program",
                accessible_functions=accessible,
                permission=PLATFORM_PERMISSION_READ,
            )
        )

        # author owns user_function and provider_function, no group → only own
        assert user_function in result
        assert provider_function in result

    def test_none_accessible_functions(self, author, provider_function, user_function):
        """When accessible_functions=None, falls back to Django groups."""
        result = list(
            Program.objects.with_permission(
                author=author,
                legacy_permission_name="view_program",
            )
        )

        assert user_function in result
        assert provider_function in result


class TestGetFunctionByPermissionRuntimeApiClient:
    def test_returns_function(self, author, other_user, provider, provider_function):
        """When has_response=True and permission present, returns the function."""
        entry = _entry("my-provider", "my-function", {PLATFORM_PERMISSION_READ})
        accessible = FunctionAccessResult(has_response=True, functions=[entry])

        result = Program.objects.get_function_by_permission(
            user=other_user,
            legacy_permission_name="view_program",
            function_title="my-function",
            provider_name="my-provider",
            accessible_functions=accessible,
            permission=PLATFORM_PERMISSION_READ,
        )

        assert result == provider_function

    def test_returns_none_without_permission(self, author, other_user, provider, provider_function):
        """When has_response=True but permission missing from entry, returns None."""
        entry = _entry("my-provider", "my-function", {PLATFORM_PERMISSION_RUN})
        accessible = FunctionAccessResult(has_response=True, functions=[entry])

        result = Program.objects.get_function_by_permission(
            user=other_user,
            legacy_permission_name="view_program",
            function_title="my-function",
            provider_name="my-provider",
            accessible_functions=accessible,
            permission=PLATFORM_PERMISSION_READ,
        )

        assert result is None

    def test_returns_none_when_entry_missing(self, author, other_user, provider, provider_function):
        """When has_response=True but entry not found, returns None."""
        accessible = FunctionAccessResult(has_response=True, functions=[])

        result = Program.objects.get_function_by_permission(
            user=other_user,
            legacy_permission_name="view_program",
            function_title="my-function",
            provider_name="my-provider",
            accessible_functions=accessible,
            permission=PLATFORM_PERMISSION_READ,
        )

        assert result is None

    def test_no_provider_returns_own_function(self, author):
        """When provider_name is None, returns user's own function regardless of accessible_functions."""
        own_fn = Program.objects.create(title="own-fn", author=author)
        accessible = FunctionAccessResult(has_response=True, functions=[])

        result = Program.objects.get_function_by_permission(
            user=author,
            legacy_permission_name="view_program",
            function_title="own-fn",
            provider_name=None,
            accessible_functions=accessible,
            permission=PLATFORM_PERMISSION_READ,
        )

        assert result == own_fn


class TestGetFunctionByPermissionFallback:
    def test_none_accessible(self, author, other_user, provider, provider_function):
        """When accessible_functions=None, falls back to Django groups (no group → None for provider fn)."""
        result = Program.objects.get_function_by_permission(
            user=other_user,
            legacy_permission_name="view_program",
            function_title="my-function",
            provider_name="my-provider",
        )

        # other_user is not the author and has no group with view_program → None
        assert result is None
