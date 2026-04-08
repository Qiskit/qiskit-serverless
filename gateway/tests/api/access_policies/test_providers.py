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
