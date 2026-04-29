"""Tests for FunctionsQuerySet model manager."""

# pylint: disable=unused-argument
import pytest
from django.contrib.auth.models import User

from core.models import Program, Provider

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


class TestWithPermissionFilterFunctionNames:
    def test_returns_own_and_permitted(self, author, other_user, provider, provider_function, user_function):
        """When filter_function_names provided, returns own functions + matched provider functions."""
        filter_fns = {"my-provider": {"my-function"}}

        result = list(
            Program.objects.with_permission(
                author=other_user,
                legacy_permission_name="view_program",
                filter_function_names=filter_fns,
            )
        )

        assert provider_function in result

    def test_excludes_function_not_in_filter(self, author, other_user, provider, provider_function):
        """When filter_function_names doesn't include the function, it's excluded."""
        filter_fns = {"my-provider": {"other-function"}}

        result = list(
            Program.objects.with_permission(
                author=other_user,
                legacy_permission_name="view_program",
                filter_function_names=filter_fns,
            )
        )

        assert provider_function not in result

    def test_empty_dict_returns_only_own(self, author, other_user, user_function):
        """When filter_function_names is empty dict, returns only own functions."""
        own_function = Program.objects.create(title="my-own", author=other_user)
        result = list(
            Program.objects.with_permission(
                author=other_user,
                legacy_permission_name="view_program",
                filter_function_names={},
            )
        )

        assert own_function in result
        assert user_function not in result


class TestWithPermissionFallback:
    def test_none_filter_uses_django_groups(self, author, provider_function, user_function):
        """When filter_function_names=None, falls back to Django groups."""
        result = list(
            Program.objects.with_permission(
                author=author,
                legacy_permission_name="view_program",
            )
        )

        # author owns user_function and provider_function
        assert user_function in result
        assert provider_function in result


class TestGetFunctionByPermissionFilterFunctionNames:
    def test_returns_function_when_in_filter(self, author, other_user, provider, provider_function):
        """When function is in filter_function_names, returns it."""
        filter_fns = {"my-provider": {"my-function"}}

        result = Program.objects.get_function_by_permission(
            user=other_user,
            legacy_permission_name="view_program",
            function_title="my-function",
            provider_name="my-provider",
            filter_function_names=filter_fns,
        )

        assert result == provider_function

    def test_returns_none_when_not_in_filter(self, author, other_user, provider, provider_function):
        """When function is not in filter_function_names, returns None."""
        filter_fns = {"my-provider": {"other-function"}}

        result = Program.objects.get_function_by_permission(
            user=other_user,
            legacy_permission_name="view_program",
            function_title="my-function",
            provider_name="my-provider",
            filter_function_names=filter_fns,
        )

        assert result is None

    def test_returns_none_when_provider_not_in_filter(self, author, other_user, provider, provider_function):
        """When provider is not in filter_function_names, returns None."""
        filter_fns = {"other-provider": {"my-function"}}

        result = Program.objects.get_function_by_permission(
            user=other_user,
            legacy_permission_name="view_program",
            function_title="my-function",
            provider_name="my-provider",
            filter_function_names=filter_fns,
        )

        assert result is None

    def test_no_provider_returns_own_function(self, author):
        """When provider_name is None, returns user's own function."""
        own_fn = Program.objects.create(title="own-fn", author=author)

        result = Program.objects.get_function_by_permission(
            user=author,
            legacy_permission_name="view_program",
            function_title="own-fn",
            provider_name=None,
            filter_function_names={"x": {"y"}},
        )

        assert result == own_fn


class TestGetFunctionByPermissionFallback:
    def test_none_filter_uses_django_groups(self, author, other_user, provider, provider_function):
        """When filter_function_names=None, falls back to Django groups (no group → None)."""
        result = Program.objects.get_function_by_permission(
            user=other_user,
            legacy_permission_name="view_program",
            function_title="my-function",
            provider_name="my-provider",
        )

        # other_user is not the author and has no group with view_program → None
        assert result is None
