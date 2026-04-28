"""Tests scheduling."""

import tempfile
from unittest.mock import MagicMock, patch
from prometheus_client import CollectorRegistry

import pytest
from django.core.management import call_command
from ray.dashboard.modules.job.common import JobStatus
from rest_framework.test import APITestCase

from core.models import Job, ComputeResource, JobEvent
from core.services.runners import RunnerError
from core.services.storage.logs_storage import LogsStorage

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics

from scheduler.schedule import get_jobs_to_schedule_fair_share, execute_job
from scheduler.tasks.update_jobs_statuses import UpdateJobsStatuses

from tests.utils import TestUtils


class TestScheduleApi(APITestCase):
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

    @patch("scheduler.schedule.get_runner")
    def test_execute_job_success(self, mock_get_runner_client):
        """Tests successful job execution via runner.submit()."""
        mock_compute_resource = MagicMock(spec=ComputeResource)
        mock_compute_resource.title = "test-cluster"

        mock_runner = MagicMock()
        mock_get_runner_client.return_value = mock_runner

        job = MagicMock()
        job.status = Job.QUEUED
        job.logs = ""
        job.compute_resource = mock_compute_resource

        ret_job = execute_job(job)

        mock_runner.submit.assert_called_once()
        mock_compute_resource.save.assert_called_once()
        assert ret_job.status == Job.PENDING

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

    @patch("scheduler.tasks.update_jobs_statuses.get_runner")
    def test_job_runtime_limit(self, get_runner):
        """Tests job runtime limit enforcement.

        This test verifies that UpdateJobStatuses correctly identifies jobs
        that have exceeded the PROGRAM_TIMEOUT setting.
        """
        runner = MagicMock()
        runner.status.return_value = JobStatus.RUNNING
        runner.logs.return_value = "No logs yet.\nMaximum job runtime reached. Stopping the job."
        get_runner.return_value = runner

        # Override PROGRAM_TIMEOUT to 0 hours so job immediately exceeds limit
        with self.settings(PROGRAM_TIMEOUT=0):
            # Create test user and authenticate
            user = TestUtils.authorize_client(user="test_limit_user", client=self.client)

            # Create a private program for the job. If provider is given, the public logs will be empty.
            program = TestUtils.create_program(
                program_title="Timeout-Test-Program",
                author=user,
            )

            compute_resource = ComputeResource.objects.create(title="test-cluster-test-job-id", active=True)
            # Create a job with RUNNING status
            # TestUtils.create_job automatically creates a JobEvent with current timestamp for creation and add a
            # JobEvent with change STATUS_CHANGE because the status is not Job.PENDING.
            job = TestUtils.create_job(
                author=user, status=Job.RUNNING, program=program, compute_resource=compute_resource
            )
            job_event = JobEvent.objects.filter(job=job).first()

            # Job status is RUNNING.
            assert job_event.data["status"] == Job.RUNNING

            # Running job status update which verify that will change the job status (timeout exceeded)
            # Since PROGRAM_TIMEOUT=0, any job with a JobEvent will have exceeded the limit
            UpdateJobsStatuses(kill_signal=KillSignal(), metrics=SchedulerMetrics(CollectorRegistry())).run()
            job.refresh_from_db()
            job_event = JobEvent.objects.filter(job=job).first()

            assert job_event.data["status"] == Job.STOPPED
            # Since the job is in terminal state, its `logs` attribute instance is empty.
            # We need to check the logs in storage
            assert (
                "Maximum job runtime reached" in LogsStorage(job).get_public_logs()
            ), "Job logs should contain timeout message"

            job_events = JobEvent.objects.filter(job=job).order_by("created")
            # The table was filled as following: Job creation, Job status change to running, job stopping
            # due exceeding time limit.
            assert len(job_events) == 3
