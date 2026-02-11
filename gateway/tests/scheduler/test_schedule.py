"""Tests scheduling."""

import tempfile
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from api.models import Job
from scheduler.schedule import get_jobs_to_schedule_fair_share, execute_job


class TestScheduleApi(APITestCase):
    """TestScheduleApi."""

    fixtures = ["tests/fixtures/schedule_fixtures.json"]

    def setUp(self):
        super().setUp()
        self._temp_directory = tempfile.TemporaryDirectory()
        self.MEDIA_ROOT = self._temp_directory.name

    def tearDown(self):
        self._temp_directory.cleanup()
        super().tearDown()

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

    @patch("core.services.ray.get_job_handler")
    def test_create_different_compute_resources(self, mock_handler):
        """Tests should create new resource."""
        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            user = get_user_model().objects.filter(username="test3_user").first()

            job_1 = MagicMock()
            job_1.author = user
            ret_job_1 = execute_job(job_1)

            job_2 = MagicMock()
            job_2.author = user
            ret_job_2 = execute_job(job_2)

            self.assertNotEqual(
                str(ret_job_1.compute_resource.id), str(ret_job_2.compute_resource.id)
            )
