"""Tests for commands."""

import os
from datetime import datetime, timezone
from typing import Optional

import pytest
from django.conf import settings as dj_settings
from ray.dashboard.modules.job.common import JobStatus
from unittest.mock import patch, MagicMock

from prometheus_client import CollectorRegistry

from core.model_managers.job_events import JobEventContext, JobEventOrigin, JobEventType
from core.models import ComputeResource, Job, JobEvent, Config
from core.services.runners import RunnerError
from core.utils import check_logs
from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.tasks.update_jobs_statuses import UpdateJobsStatuses
from scheduler.tasks.free_resources import FreeResources
from scheduler.tasks.schedule_queued_jobs import ScheduleQueuedJobs
from scheduler.schedule import get_jobs_to_schedule_fair_share
from tests.utils import TestUtils


class TestCommands:
    """Tests for commands."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, settings, db):
        """Setup test environment."""
        settings.MEDIA_ROOT = str(tmp_path)
        Config.add_defaults()
        self.metrics = SchedulerMetrics(CollectorRegistry())

    def test_free_resources(self):
        """Tests free resources command."""
        # Create compute resource matching fixture data
        test3_user = TestUtils.get_user_and_username("test3_user")[0]
        TestUtils.get_or_create_compute_resource(title="compute resource", host="somehost", owner=test3_user)

        FreeResources(kill_signal=KillSignal(), metrics=self.metrics).run()
        num_resources = ComputeResource.objects.count()
        assert num_resources == 1

    @patch("scheduler.tasks.update_jobs_statuses.get_runner")
    def test_update_jobs_statuses(self, get_runner):
        """Tests update of job statuses."""
        # Test status change from PENDING to RUNNING
        runner = MagicMock()
        runner.status.return_value = JobStatus.RUNNING
        runner.logs.return_value = "No logs yet."
        get_runner.return_value = runner

        job = self._create_test_job(ray_job_id="test_update_jobs_statuses")

        UpdateJobsStatuses(kill_signal=KillSignal(), metrics=self.metrics).run()

        job.refresh_from_db()
        assert job.status == "RUNNING"
        assert job.env_vars is not None

        job_events = JobEvent.objects.filter(job=job)
        assert len(job_events) == 3  # creation (QUEUED) + status change (PENDING) + status change (RUNNING)
        assert job_events[0].event_type == JobEventType.STATUS_CHANGE
        assert job_events[0].data["status"] == JobStatus.RUNNING
        assert job_events[0].origin == JobEventOrigin.SCHEDULER
        assert job_events[0].context == JobEventContext.UPDATE_JOB_STATUS

        # Test job logs for FAILED job with empty logs
        runner.status.return_value = JobStatus.FAILED
        runner.logs.return_value = ""

        UpdateJobsStatuses(kill_signal=KillSignal(), metrics=self.metrics).run()

        job.refresh_from_db()
        assert job.status == "FAILED"
        assert job.env_vars == "{}"
        assert job.sub_status is None

        job_events = JobEvent.objects.filter(job=job).order_by("created")
        assert len(job_events) == 4
        assert job_events[3].event_type == JobEventType.STATUS_CHANGE
        assert job_events[3].data["status"] == JobStatus.FAILED
        assert job_events[3].origin == JobEventOrigin.SCHEDULER
        assert job_events[3].context == JobEventContext.UPDATE_JOB_STATUS

    @patch("scheduler.tasks.schedule_queued_jobs.execute_job")
    def test_schedule_queued_jobs(self, execute_job):
        """Tests schedule of queued jobs command."""
        # Create test data to match fixture expectations (7 jobs total)
        test_user = TestUtils.get_user_and_username("test_user")[0]
        test2_user = TestUtils.get_user_and_username("test2_user")[0]
        test3_user = TestUtils.get_user_and_username("test3_user")[0]
        test4_user = TestUtils.get_user_and_username("test4_user")[0]

        program = TestUtils.create_program(program_title="Program", author=test_user)
        compute_resource = TestUtils.get_or_create_compute_resource(
            title="compute resource", host="somehost", owner=test3_user
        )

        # Create 7 jobs with various statuses
        job1 = TestUtils.create_job(author=test_user, program=program, status=Job.QUEUED, result='{"somekey":1}')
        TestUtils.create_job(author=test_user, program=program, status=Job.QUEUED, result='{"somekey":1}')
        TestUtils.create_job(author=test2_user, program=program, status=Job.PENDING, result='{"somekey":1}')
        TestUtils.create_job(
            author=test3_user,
            program=program,
            status=Job.PENDING,
            compute_resource=compute_resource,
            result='{"somekey":1}',
        )
        TestUtils.create_job(author=test3_user, program=program, status=Job.RUNNING, result='{"somekey":1}')
        TestUtils.create_job(author=test4_user, program=program, status=Job.QUEUED, result='{"somekey":1}')
        TestUtils.create_job(author=test4_user, program=program, status=Job.QUEUED, result='{"somekey":1}')

        fake_job = MagicMock()
        fake_job.id = job1.id
        fake_job.logs = ""
        fake_job.status = "SUCCEEDED"
        fake_job.sub_status = None
        fake_job.program.artifact.path = "non_existing_file.tar"
        fake_job.save.return_value = None
        fake_job.created = datetime.now(timezone.utc)
        fake_job.gpu = False
        fake_job.ray_job_id = None
        fake_job.compute_resource = None
        fake_job.fleet_id = None

        execute_job.return_value = fake_job
        ScheduleQueuedJobs(kill_signal=KillSignal(), metrics=self.metrics).run()
        # TODO: mock execute job to change status of job and query for QUEUED jobs  # pylint: disable=fixme
        job_count = Job.objects.count()
        assert job_count == 7

        job_events = JobEvent.objects.filter(job_id=fake_job.id)
        # job1 is in QUEUED state and from its creation it has 1 corresponding JobEvent.
        # It calls `execute_job` twice and add 2 equal events.
        assert len(job_events) == 3
        assert job_events[0].event_type == JobEventType.STATUS_CHANGE
        assert job_events[0].data["status"] == JobStatus.SUCCEEDED
        assert job_events[0].origin == JobEventOrigin.SCHEDULER
        assert job_events[0].context == JobEventContext.SCHEDULE_JOBS
        assert job_events[1].event_type == JobEventType.STATUS_CHANGE
        assert job_events[1].data["status"] == JobStatus.SUCCEEDED
        assert job_events[1].origin == JobEventOrigin.SCHEDULER
        assert job_events[1].context == JobEventContext.SCHEDULE_JOBS

    def test_schedule_queued_jobs_separates_gpu_and_cpu_queues(self):
        """Tests that GPU and CPU jobs are scheduled from separate queues."""
        cpu_job = self._create_test_job(author="cpu_user", status=Job.QUEUED, gpu=False)
        gpu_job = self._create_test_job(author="gpu_user", status=Job.QUEUED, gpu=True)

        cpu_jobs = get_jobs_to_schedule_fair_share(slots=10, gpu=False)
        gpu_jobs = get_jobs_to_schedule_fair_share(slots=10, gpu=True)

        assert cpu_job in cpu_jobs
        assert gpu_job not in cpu_jobs
        assert gpu_job in gpu_jobs
        assert cpu_job not in gpu_jobs

    def test_check_empty_logs(self):
        """Test error notification for failed and empty logs."""
        job = MagicMock()
        job.id = "42"
        job.status = "FAILED"
        logs = check_logs(logs="", job=job)
        assert logs == "Job 42 failed due to an internal error."

    def test_check_non_empty_logs(self):
        """Test logs checker for non empty logs."""
        job = MagicMock()
        job.id = "42"
        job.status = "FAILED"
        logs = check_logs(logs="awsome logs", job=job)
        assert logs == "awsome logs"

    def test_check_long_logs(self, settings):
        """Test logs checker for very long logs in this case more than 1MB."""
        settings.FUNCTIONS_LOGS_SIZE_LIMIT = 100
        job = MagicMock()
        job.id = "42"
        job.status = "RUNNING"
        log_to_test = "A" * 120 + "B"
        logs = check_logs(logs=log_to_test, job=job)
        assert (
            "[Logs exceeded maximum allowed size (9.5367431640625e-05 MB). Logs have been truncated, discarding the oldest entries first.]"
            in logs
        )
        assert "AAAAAAAAAAB" in logs

    @patch("scheduler.tasks.update_jobs_statuses.get_runner")
    def test_update_jobs_statuses_filters_logs_user_function(self, get_runner, settings):
        """Tests that logs are filtered when saving for function without provider."""
        compute_resource = TestUtils.get_or_create_compute_resource(title="test-cluster-user-logs", active=True)
        job = self._create_test_job(
            author="test_author",
            status=Job.RUNNING,
            compute_resource=compute_resource,
            ray_job_id="test-ray-job-id",
        )

        job_events = JobEvent.objects.filter(job=job)
        running_jobs = Job.objects.filter(status__in=Job.RUNNING_STATUSES)
        assert len(job_events) == 2  # the events are: creation (QUEUED), running
        assert len(running_jobs) == 1

        # Mock Ray to return unfiltered logs with PUBLIC and PRIVATE markers
        full_logs = """
2026-01-06 10:00:00,000 INFO job_manager.py:568 -- Runtime env is setting up.

[PUBLIC] INFO: Public user log
[PRIVATE] INFO: Private provider log
[PUBLIC] INFO: Another public log
Ray internal log without marker
[PUBLIC] INFO: Final public log
"""

        runner = MagicMock()
        runner.status.return_value = JobStatus.SUCCEEDED
        runner.logs.return_value = full_logs
        get_runner.return_value = runner

        UpdateJobsStatuses(kill_signal=KillSignal(), metrics=self.metrics).run()

        # User logs are located in username/logs/
        # Verify user logs are filtered: [PUBLIC] only lines without the [PUBLIC]
        user_log_file_path = os.path.join(
            dj_settings.MEDIA_ROOT,
            "test_author",
            "logs",
            f"{job.id}.log",
        )
        expected_user_logs = """
2026-01-06 10:00:00,000 INFO job_manager.py:568 -- Runtime env is setting up.

INFO: Public user log
INFO: Private provider log
INFO: Another public log
Ray internal log without marker
INFO: Final public log
"""

        with open(user_log_file_path, "r", encoding="utf-8") as log_file:
            saved_user_logs = log_file.read()
        assert saved_user_logs == expected_user_logs

        private_log_file_path = os.path.join(
            dj_settings.MEDIA_ROOT,
            "program-test_author-custom",
            "logs",
            f"{job.id}.log",
        )
        # private log shouldn't exist
        assert not os.path.exists(private_log_file_path)

        job.refresh_from_db()
        assert job.logs == ""

    @patch("scheduler.tasks.update_jobs_statuses.get_runner")
    def test_update_jobs_statuses_filters_logs_provider_function(self, get_runner, settings):
        """Tests that logs are filtered when saving for function with provider."""
        compute_resource = TestUtils.get_or_create_compute_resource(title="test-cluster-provider-logs", active=True)
        job = self._create_test_job(
            author="test_author",
            provider_admin="test_provider",
            status=Job.RUNNING,
            compute_resource=compute_resource,
            ray_job_id="test-ray-job-id-with-provider",
        )

        # Mock Ray to return unfiltered logs
        full_logs = """
[PUBLIC] INFO: Public log for user

[PRIVATE] INFO: Private log for provider only
[PUBLIC] INFO: Another public log
Internal system log
[PRIVATE] WARNING: Private warning
[PUBLIC] INFO: Final public log
"""

        runner = MagicMock()
        runner.status.return_value = JobStatus.SUCCEEDED
        runner.logs.return_value = full_logs
        get_runner.return_value = runner

        UpdateJobsStatuses(kill_signal=KillSignal(), metrics=self.metrics).run()

        # User logs are located in username/provider/function/logs/ for provider jobs
        # Verify user logs are filtered: [PUBLIC] only lines without the [PUBLIC]
        user_log_file_path = os.path.join(
            dj_settings.MEDIA_ROOT,
            "test_author",
            "test_provider",
            "program-test_author-test_provider",
            "logs",
            f"{job.id}.log",
        )
        expected_user_logs = """INFO: Public log for user
INFO: Another public log
INFO: Final public log
"""
        expected_provider_logs = """

INFO: Private log for provider only
Internal system log
WARNING: Private warning
"""

        with open(user_log_file_path, "r", encoding="utf-8") as log_file:
            saved_user_logs = log_file.read()
        assert saved_user_logs == expected_user_logs

        # Verify provider logs contain everything: [PUBLIC], [PRIVATE] and internal logs...
        provider_log_file_path = os.path.join(
            dj_settings.MEDIA_ROOT,
            "test_provider",
            "program-test_author-test_provider",
            "logs",
            f"{job.id}.log",
        )

        with open(provider_log_file_path, "r", encoding="utf-8") as log_file:
            saved_provider_logs = log_file.read()
        assert saved_provider_logs == expected_provider_logs

    @patch("scheduler.tasks.update_jobs_statuses.get_runner")
    def test_update_jobs_statuses_job_handler_status_error_status_event(self, get_runner, settings):
        """Tests that the job_event is stored when runner.status() raises exception."""
        compute_resource = TestUtils.get_or_create_compute_resource(title="test-cluster-provider-logs", active=True)
        job = self._create_test_job(
            author="test_author",
            provider_admin="test_provider",
            status=Job.RUNNING,
            compute_resource=compute_resource,
            ray_job_id="test-ray-job-id-with-provider",
        )

        runner = MagicMock()
        runner.status.side_effect = RunnerError("Error")
        get_runner.return_value = runner

        UpdateJobsStatuses(kill_signal=KillSignal(), metrics=self.metrics).run()

        job_events = JobEvent.objects.filter(job=job.id)
        assert len(job_events) == 3  # the events are: creation, running, failed
        assert job_events[0].event_type == JobEventType.STATUS_CHANGE
        assert job_events[0].data["status"] == Job.FAILED
        assert job_events[0].origin == JobEventOrigin.SCHEDULER
        assert job_events[0].context == JobEventContext.UPDATE_JOB_STATUS

    def _create_test_job(  # pylint: disable=too-many-positional-arguments
        self,
        author: str = "test_author",
        provider_admin: Optional[str] = None,
        status: str = Job.PENDING,
        compute_resource: Optional[ComputeResource] = None,
        ray_job_id: str = "test-job-id",
        gpu: bool = False,
        logs: str = "No logs yet.",
    ) -> Job:
        """Helper method to create a test job.

        Args:
            author: Username for the job author
            provider_admin: If set, creates a provider and assigns admin rights
            status: Job status (default: PENDING)
            compute_resource: ComputeResource to use (creates new one if None)
            ray_job_id: Ray job ID
            gpu: Whether this is a GPU job
        """
        if compute_resource is None:
            compute_resource = TestUtils.get_or_create_compute_resource(title=f"test-cluster-{ray_job_id}", active=True)

        author_user, _ = TestUtils.get_user_and_username(author=author)
        provider = None

        if provider_admin:
            TestUtils.add_user_to_group(provider_admin, provider_admin)
            provider = TestUtils.get_or_create_provider(provider_admin, provider_admin)

        program = TestUtils.create_program(
            program_title=f"program-{author_user.username}-{provider_admin or 'custom'}",
            author=author_user,
            provider=provider,
        )

        return TestUtils.create_job(
            author=author_user,
            program=program,
            status=status,
            compute_resource=compute_resource,
            ray_job_id=ray_job_id,
            gpu=gpu,
            logs=logs,
        )
