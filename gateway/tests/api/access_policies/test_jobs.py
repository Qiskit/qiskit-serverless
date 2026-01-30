from django.contrib.auth.models import User, Group
from django.test import TestCase

from api.access_policies.jobs import JobAccessPolicies
from api.models import Program, Job, Provider


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

    def test_can_access_validates_parameters(self):
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

    def test_author_can_access_results_and_update_sub_status(self):
        """Test that can_read_result, can_save_result and can_update_sub_status returns True for job author."""
        self.assertTrue(JobAccessPolicies.can_read_result(self.job_author, self.job))
        self.assertTrue(JobAccessPolicies.can_save_result(self.job_author, self.job))

        self.assertTrue(
            JobAccessPolicies.can_update_sub_status(self.job_author, self.job)
        )

    def test_non_author_cannot_access_results_and_update_sub_status(self):
        """Test that can_read_result, can_save_result and can_update_sub_status returns False for non author."""
        self.assertFalse(JobAccessPolicies.can_read_result(self.other_user, self.job))
        self.assertFalse(JobAccessPolicies.can_save_result(self.other_user, self.job))

        self.assertFalse(
            JobAccessPolicies.can_update_sub_status(self.other_user, self.job)
        )
