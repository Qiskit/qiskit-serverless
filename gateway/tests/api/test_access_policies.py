"""Tests for access policies."""

from django.contrib.auth.models import Group, User

from django.test import TestCase

from api.access_policies.jobs import JobAccessPolicies
from api.access_policies.providers import ProviderAccessPolicy
from api.access_policies.users import UserAccessPolicies
from api.models import Job, Program, Provider


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


class TestProviderAccessPolicy(TestCase):
    """Tests for ProviderAccessPolicy."""

    def test_can_access_error(self):
        """ValueError when provider is None."""
        user = User.objects.create_user(username="u")
        with self.assertRaises(ValueError):
            ProviderAccessPolicy.can_access(user, None)

    def test_can_access(self):
        """can_access is True if the user has a group in common with the provider."""

        user = User.objects.create_user(username="u")
        provider = Provider.objects.create(name="p")

        # group shared between user and provider means admin
        admin_group = Group.objects.create(name="same group shared")
        user.groups.add(admin_group)
        provider.admin_groups.add(admin_group)

        self.assertTrue(ProviderAccessPolicy.can_access(user, provider))

    def test_can_access_returns_false_if_user_not_in_admin_groups_no_groups(self):
        """can_access is False if the user doesn't have a group in common with the provider."""

        user = User.objects.create_user(username="u")
        provider = Provider.objects.create(name="p")
        self.assertFalse(ProviderAccessPolicy.can_access(user, provider))

    def test_can_access_returns_false_if_user_not_in_admin_groups(self):
        """can_access is False if the user doesn't have a group in common with the provider."""
        user = User.objects.create_user(username="u")
        user.groups.add(Group.objects.create(name="user_group1"))
        user.groups.add(Group.objects.create(name="user_group2"))

        provider = Provider.objects.create(name="p")
        provider.admin_groups.add(Group.objects.create(name="admin_group1"))
        provider.admin_groups.add(Group.objects.create(name="admin_group2"))

        self.assertFalse(ProviderAccessPolicy.can_access(user, provider))


class TestJobAccessPolicies(TestCase):
    """Tests for JobAccessPolicies."""

    def setUp(self):
        """Set up test data."""
        self.job_author = User.objects.create_user(username="author")
        self.program = Program.objects.create(title="Program", author=self.job_author)
        self.job = Job.objects.create(
            program=self.program,
            author=self.job_author,
            status=Job.QUEUED,
        )

        self.other_user = User.objects.create_user(username="who knows")

    def test_can_access_raises_if_user_is_none(self):
        """ValueError when user is None, author or job is None."""
        with self.assertRaises(ValueError):
            JobAccessPolicies.can_access(None, self.job)

        with self.assertRaises(ValueError):
            JobAccessPolicies.can_access(self.job_author, None)

    def test_can_access_returns_true_for_author(self):
        """Test that can_access returns True when user is the job author."""
        self.assertTrue(JobAccessPolicies.can_access(self.job_author, self.job))

    def test_can_access_returns_false_for_non_author(self):
        """Test that can_access returns False when user is not the author."""
        self.assertFalse(JobAccessPolicies.can_access(self.other_user, self.job))

    def test_can_access_returns_true_for_provider_admin(self):
        """Test that can_access returns True for provider admin on provider job."""
        admin_user = User.objects.create_user(username="admin")
        provider = Provider.objects.create(name="p")

        admin_group = Group.objects.create(name="same group shared")
        admin_user.groups.add(admin_group)
        provider.admin_groups.add(admin_group)

        provider_program = Program.objects.create(
            title="Program", author=self.job_author, provider=provider
        )
        provider_job = Job.objects.create(
            program=provider_program,
            author=self.job_author,
            status=Job.QUEUED,
        )

        self.assertTrue(JobAccessPolicies.can_access(admin_user, provider_job))

    def test_can_read_result_returns_true_for_author(self):
        """Test that can_read_result returns True for job author."""
        self.assertTrue(JobAccessPolicies.can_read_result(self.job_author, self.job))
        self.assertTrue(JobAccessPolicies.can_save_result(self.job_author, self.job))

        self.assertFalse(JobAccessPolicies.can_read_result(self.other_user, self.job))
        self.assertFalse(JobAccessPolicies.can_save_result(self.other_user, self.job))

        self.assertTrue(
            JobAccessPolicies.can_update_sub_status(self.job_author, self.job)
        )
        self.assertFalse(
            JobAccessPolicies.can_update_sub_status(self.other_user, self.job)
        )
