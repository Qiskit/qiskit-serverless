"""Tests for access policies."""

import pytest

from django.contrib.auth.models import Group, User

from api.access_policies.providers import ProviderAccessPolicy
from core.models import Provider

pytestmark = pytest.mark.django_db


def test_can_access_error():
    """ValueError when provider is None."""
    user = User.objects.create_user(username="u")
    with pytest.raises(ValueError):
        ProviderAccessPolicy.can_access(user, None)


def test_can_access():
    """can_access is True if the user has a group in common with the provider."""

    user = User.objects.create_user(username="u")
    provider = Provider.objects.create(name="p")

    # group shared between user and provider means admin
    admin_group = Group.objects.create(name="same group shared")
    user.groups.add(admin_group)
    provider.admin_groups.add(admin_group)

    assert ProviderAccessPolicy.can_access(user, provider) is True


def test_can_access_returns_false_if_user_not_in_admin_groups_no_groups():
    """can_access is False if the user doesn't have a group in common with the provider."""

    user = User.objects.create_user(username="u")
    provider = Provider.objects.create(name="p")
    assert ProviderAccessPolicy.can_access(user, provider) is False


def test_can_access_returns_false_if_user_not_in_admin_groups():
    """can_access is False if the user doesn't have a group in common with the provider."""
    user = User.objects.create_user(username="u")
    user.groups.add(Group.objects.create(name="user_group1"))
    user.groups.add(Group.objects.create(name="user_group2"))

    provider = Provider.objects.create(name="p")
    provider.admin_groups.add(Group.objects.create(name="admin_group1"))
    provider.admin_groups.add(Group.objects.create(name="admin_group2"))

    assert ProviderAccessPolicy.can_access(user, provider) is False


from api.domain.authorization.function_access_entry import FunctionAccessEntry
from api.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Job, PLATFORM_PERMISSION_PROVIDER_UPLOAD, PLATFORM_PERMISSION_PROVIDER_JOBS


def _entry(provider_name, permissions):
    return FunctionAccessEntry(
        provider_name=provider_name,
        function_title="some-fn",
        permissions=permissions,
        business_model=Job.BUSINESS_MODEL_SUBSIDIZED,
    )


def test_can_access_external_client_returns_true_when_permission_present():
    """can_access is True when external client has the permission for the provider."""
    user = User.objects.create_user(username="u_ext")
    provider = Provider.objects.create(name="my-provider")

    entry = _entry("my-provider", {PLATFORM_PERMISSION_PROVIDER_UPLOAD})
    accessible = FunctionAccessResult(has_response=True, functions=[entry])

    assert (
        ProviderAccessPolicy.can_access(
            user,
            provider,
            accessible_functions=accessible,
            permission=PLATFORM_PERMISSION_PROVIDER_UPLOAD,
        )
        is True
    )


def test_can_access_external_client_returns_false_when_permission_missing():
    """can_access is False when external client has no entry with the permission."""
    user = User.objects.create_user(username="u_ext2")
    provider = Provider.objects.create(name="my-provider2")

    entry = _entry("my-provider2", {PLATFORM_PERMISSION_PROVIDER_JOBS})
    accessible = FunctionAccessResult(has_response=True, functions=[entry])

    assert (
        ProviderAccessPolicy.can_access(
            user,
            provider,
            accessible_functions=accessible,
            permission=PLATFORM_PERMISSION_PROVIDER_UPLOAD,
        )
        is False
    )


def test_can_access_external_client_returns_false_when_no_entries():
    """can_access is False when external client returns no entries for provider."""
    user = User.objects.create_user(username="u_ext3")
    provider = Provider.objects.create(name="my-provider3")

    accessible = FunctionAccessResult(has_response=True, functions=[])

    assert (
        ProviderAccessPolicy.can_access(
            user,
            provider,
            accessible_functions=accessible,
            permission=PLATFORM_PERMISSION_PROVIDER_UPLOAD,
        )
        is False
    )


def test_can_access_external_none_accessible_functions_uses_fallback():
    """can_access falls back to Django groups when accessible_functions=None."""
    user = User.objects.create_user(username="u_fallback")
    provider = Provider.objects.create(name="fallback-provider")

    admin_group = Group.objects.create(name="fallback_group")
    user.groups.add(admin_group)
    provider.admin_groups.add(admin_group)

    assert (
        ProviderAccessPolicy.can_access(
            user,
            provider,
            accessible_functions=None,
            permission=PLATFORM_PERMISSION_PROVIDER_UPLOAD,
        )
        is True
    )


def test_can_access_has_response_false_uses_groups_fallback():
    """can_access falls back to Django groups when has_response=False."""
    user = User.objects.create_user(username="u_fallback2")
    provider = Provider.objects.create(name="fallback-provider2")

    admin_group = Group.objects.create(name="fallback_group2")
    user.groups.add(admin_group)
    provider.admin_groups.add(admin_group)

    accessible = FunctionAccessResult(has_response=False)

    assert (
        ProviderAccessPolicy.can_access(
            user,
            provider,
            accessible_functions=accessible,
            permission=PLATFORM_PERMISSION_PROVIDER_UPLOAD,
        )
        is True
    )
