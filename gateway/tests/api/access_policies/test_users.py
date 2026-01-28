from django.contrib.auth.models import User
from django.test import TestCase

from api.access_policies.users import UserAccessPolicies


class TestUserAccessPolicies(TestCase):
    """Tests for UserAccessPolicies."""

    def test_can_access_error(self):
        """ValueError when user is None."""
        with self.assertRaises(ValueError):
            UserAccessPolicies.can_access(None)

    def test_can_access(self):
        """Return true if user is active"""
        user = User.objects.create_user(username="active_user", is_active=True)
        self.assertTrue(UserAccessPolicies.can_access(user))

        user = User.objects.create_user(username="inactive_user", is_active=False)
        self.assertFalse(UserAccessPolicies.can_access(user))
