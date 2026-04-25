"""Tests for FunctionsQuerySet model manager."""

# pylint: disable=unused-argument
import pytest
from django.contrib.auth.models import User

from api.domain.authorization.function_access_entry import FunctionAccessEntry
from api.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Program, Provider, Job, PLATFORM_PERMISSION_VIEW, PLATFORM_PERMISSION_RUN

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


# --- with_permission: flujo con cliente externo ---


def test_with_permission_external_returns_own_and_permitted(
    author, other_user, provider, provider_function, user_function
):
    """When has_response=True, returns own functions + permitted provider functions."""
    entry = _entry("my-provider", "my-function", {PLATFORM_PERMISSION_VIEW})
    accessible = FunctionAccessResult(has_response=True, functions=[entry])

    result = list(
        Program.objects.with_permission(
            author=other_user,
            legacy_permission_name="view_program",
            accessible_functions=accessible,
            permission=PLATFORM_PERMISSION_VIEW,
        )
    )

    assert provider_function in result


def test_with_permission_external_excludes_function_without_permission(author, other_user, provider, provider_function):
    """When has_response=True and no matching permission, provider function not returned."""
    entry = _entry("my-provider", "my-function", {PLATFORM_PERMISSION_RUN})
    accessible = FunctionAccessResult(has_response=True, functions=[entry])

    result = list(
        Program.objects.with_permission(
            author=other_user,
            legacy_permission_name="view_program",
            accessible_functions=accessible,
            permission=PLATFORM_PERMISSION_VIEW,
        )
    )

    assert provider_function not in result


def test_with_permission_external_no_entries_returns_only_own(author, other_user, user_function):
    """When has_response=True but no entries, returns only own functions."""
    accessible = FunctionAccessResult(has_response=True, functions=[])

    own_function = Program.objects.create(title="my-own", author=other_user)
    result = list(
        Program.objects.with_permission(
            author=other_user,
            legacy_permission_name="view_program",
            accessible_functions=accessible,
            permission=PLATFORM_PERMISSION_VIEW,
        )
    )

    assert own_function in result
    assert user_function not in result


def test_with_permission_fallback_when_has_response_false(author, provider_function, user_function):
    """When has_response=False, falls back to Django groups (no extra functions)."""
    accessible = FunctionAccessResult(has_response=False)

    result = list(
        Program.objects.with_permission(
            author=author,
            legacy_permission_name="view_program",
            accessible_functions=accessible,
            permission=PLATFORM_PERMISSION_VIEW,
        )
    )

    # author owns user_function and provider_function, no group → only own
    assert user_function in result
    assert provider_function in result


def test_with_permission_none_accessible_functions_uses_fallback(author, provider_function, user_function):
    """When accessible_functions=None, falls back to Django groups."""
    result = list(
        Program.objects.with_permission(
            author=author,
            legacy_permission_name="view_program",
        )
    )

    assert user_function in result
    assert provider_function in result


# --- get_function_by_permission: flujo con cliente externo ---


def test_get_function_by_permission_external_returns_function(author, other_user, provider, provider_function):
    """When has_response=True and permission present, returns the function."""
    entry = _entry("my-provider", "my-function", {PLATFORM_PERMISSION_VIEW})
    accessible = FunctionAccessResult(has_response=True, functions=[entry])

    result = Program.objects.get_function_by_permission(
        user=other_user,
        legacy_permission_name="view_program",
        function_title="my-function",
        provider_name="my-provider",
        accessible_functions=accessible,
        permission=PLATFORM_PERMISSION_VIEW,
    )

    assert result == provider_function


def test_get_function_by_permission_external_returns_none_without_permission(
    author, other_user, provider, provider_function
):
    """When has_response=True but permission missing from entry, returns None."""
    entry = _entry("my-provider", "my-function", {PLATFORM_PERMISSION_RUN})
    accessible = FunctionAccessResult(has_response=True, functions=[entry])

    result = Program.objects.get_function_by_permission(
        user=other_user,
        legacy_permission_name="view_program",
        function_title="my-function",
        provider_name="my-provider",
        accessible_functions=accessible,
        permission=PLATFORM_PERMISSION_VIEW,
    )

    assert result is None


def test_get_function_by_permission_external_returns_none_when_entry_missing(
    author, other_user, provider, provider_function
):
    """When has_response=True but entry not found, returns None."""
    accessible = FunctionAccessResult(has_response=True, functions=[])

    result = Program.objects.get_function_by_permission(
        user=other_user,
        legacy_permission_name="view_program",
        function_title="my-function",
        provider_name="my-provider",
        accessible_functions=accessible,
        permission=PLATFORM_PERMISSION_VIEW,
    )

    assert result is None


def test_get_function_by_permission_no_provider_returns_own_function(author):
    """When provider_name is None, returns user's own function regardless of accessible_functions."""
    own_fn = Program.objects.create(title="own-fn", author=author)
    accessible = FunctionAccessResult(has_response=True, functions=[])

    result = Program.objects.get_function_by_permission(
        user=author,
        legacy_permission_name="view_program",
        function_title="own-fn",
        provider_name=None,
        accessible_functions=accessible,
        permission=PLATFORM_PERMISSION_VIEW,
    )

    assert result == own_fn


def test_get_function_by_permission_fallback_none_accessible(author, other_user, provider, provider_function):
    """When accessible_functions=None, falls back to Django groups (no group → None for provider fn)."""
    result = Program.objects.get_function_by_permission(
        user=other_user,
        legacy_permission_name="view_program",
        function_title="my-function",
        provider_name="my-provider",
    )

    # other_user is not the author and has no group with view_program → None
    assert result is None
