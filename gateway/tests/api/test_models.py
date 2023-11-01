"""Tests for models."""


from rest_framework.test import APITestCase

from api.models import Job


class TestModels(APITestCase):
    """TestModels."""

    def test_job_is_terminal_state(self):
        """Tests job terminal state function."""
        job = Job()
        job.status = Job.PENDING
        self.assertFalse(job.in_terminal_state())

        job.status = Job.RUNNING
        self.assertFalse(job.in_terminal_state())

        job.status = Job.STOPPED
        self.assertTrue(job.in_terminal_state())

        job.status = Job.FAILED
        self.assertTrue(job.in_terminal_state())

        job.status = Job.SUCCEEDED
        self.assertTrue(job.in_terminal_state())
