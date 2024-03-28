"""Tests scheduling."""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from api.models import Job
from api.schedule import get_jobs_to_schedule_fair_share, execute_job


class TestScheduleApi(APITestCase):
    """TestJobApi."""

    fixtures = ["tests/fixtures/schedule_fixtures.json"]

    def test_get_fair_share_jobs(self):
        """Tests fair share jobs getter function."""
        jobs = get_jobs_to_schedule_fair_share(5)

        for job in jobs:
            self.assertIsInstance(job, Job)

        author_ids = [job.author_id for job in jobs]
        job_ids = [str(job.id) for job in jobs]
        self.assertTrue(1 in author_ids)
        self.assertTrue(4 in author_ids)
        self.assertEqual(len(jobs), 2)
        self.assertTrue("1a7947f9-6ae8-4e3d-ac1e-e7d608deec90" in job_ids)
        self.assertTrue("1a7947f9-6ae8-4e3d-ac1e-e7d608deec82" in job_ids)

    @patch("api.ray.get_job_handler")
    def test_already_created_ray_cluster_execute_job(self, mock_handler):
        """Tests should not create new resource and reuse what user already have."""
        user = get_user_model().objects.filter(username="test3_user").first()
        job = MagicMock()
        job.author = user
        ret_job = execute_job(job)
        self.assertEqual(
            str(ret_job.compute_resource.id), "1a7947f9-6ae8-4e3d-ac1e-e7d608deec99"
        )
        self.assertEqual(ret_job.status, Job.PENDING)
