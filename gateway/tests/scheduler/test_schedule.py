"""Tests scheduling."""

from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command

from core.models import Job
from core.services.runners import RunnerError
from scheduler.schedule import get_jobs_to_schedule_fair_share, execute_job
from tests.utils import TestUtils


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

    @patch("core.services.runners.ray_runner.RayRunner._submit_to_ray", return_value="test-ray-job-id")
    def test_execute_job_success(self, _mock_submit_to_ray, settings):
        """Tests that execute_job saves ray_job_id, compute_resource and PENDING status to DB."""
        settings.RAY_CLUSTER_MODE_LOCAL = True
        settings.RAY_LOCAL_HOST = "http://localhost:8265"

        job = TestUtils.create_job(author="test_user", program="test_program", status=Job.QUEUED)

        execute_job(job)

        job.refresh_from_db()
        assert job.status == Job.PENDING
        assert job.ray_job_id == "test-ray-job-id"
        assert job.compute_resource is not None
        assert job.compute_resource.host == "http://localhost:8265"

    @patch("scheduler.schedule.get_runner")
    def test_execute_job_failure(self, mock_get_runner_client):
        """Tests job execution failure handling."""
        mock_runner = MagicMock()
        mock_runner.submit.side_effect = RunnerError("Submit failed")
        mock_get_runner_client.return_value = mock_runner

        job = MagicMock()
        job.status = Job.QUEUED
        job.logs = ""

        ret_job = execute_job(job)

        mock_runner.submit.assert_called_once()
        assert ret_job.status == Job.FAILED
        assert "Compute resource creation or job submission failed" in ret_job.logs
