"""Tests scheduling."""

import pytest
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command

from core.models import Job
from scheduler.schedule import get_jobs_to_schedule_fair_share, execute_job


class TestScheduleApi:
    """TestScheduleApi."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, settings, db):
        call_command("loaddata", "tests/fixtures/schedule_fixtures.json")
        settings.MEDIA_ROOT = str(tmp_path)

    def test_get_fair_share_jobs(self):
        """Tests fair share jobs getter function."""
        jobs = get_jobs_to_schedule_fair_share(5, False)

        for job in jobs:
            assert isinstance(job, Job)

        author_ids = [job.author_id for job in jobs]
        job_ids = [str(job.id) for job in jobs]
        assert 1 in author_ids
        assert 4 in author_ids
        assert len(jobs) == 2
        assert "1a7947f9-6ae8-4e3d-ac1e-e7d608deec90" in job_ids
        assert "1a7947f9-6ae8-4e3d-ac1e-e7d608deec82" in job_ids

    @patch("core.services.ray.get_job_handler")
    def test_create_different_compute_resources(self, mock_handler):
        """Tests should create new resource."""
        user = get_user_model().objects.filter(username="test3_user").first()

        def create_resource_side_effect(job, cluster_name):
            return Job.compute_resource.field.related_model.objects.create(
                title=cluster_name,
                host="http://example",
                owner=job.author,
            )

        def submit_job_side_effect(job):
            job.status = Job.PENDING
            return job

        with patch("scheduler.schedule.create_compute_resource", side_effect=create_resource_side_effect):
            with patch("scheduler.schedule.submit_job", side_effect=submit_job_side_effect):
                job_1 = MagicMock()
                job_1.author = user
                ret_job_1 = execute_job(job_1)

                job_2 = MagicMock()
                job_2.author = user
                ret_job_2 = execute_job(job_2)

                assert str(ret_job_1.compute_resource.id) != str(ret_job_2.compute_resource.id)
