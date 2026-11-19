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
        business_model=BusinessModel.LICENSED,
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
