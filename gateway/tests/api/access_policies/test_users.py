import pytest

from django.contrib.auth.models import User

from api.access_policies.users import UserAccessPolicies

pytestmark = pytest.mark.django_db


def test_can_access_error():
    """ValueError when user is None."""
    with pytest.raises(ValueError):
        UserAccessPolicies.can_access(None)


def test_can_access():
    """Return true if user is active"""
    user = User.objects.create_user(username="active_user", is_active=True)
    assert UserAccessPolicies.can_access(user) is True

    user = User.objects.create_user(username="inactive_user", is_active=False)
    assert UserAccessPolicies.can_access(user) is False
