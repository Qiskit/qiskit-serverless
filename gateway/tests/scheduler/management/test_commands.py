"""Tests for commands."""

from typing import Optional

from django.contrib.auth.models import User, Group
from django.core.management import call_command
from ray.dashboard.modules.job.common import JobStatus
from rest_framework.test import APITestCase
from unittest.mock import patch, MagicMock

from core.model_managers.job_events import JobEventContext, JobEventOrigin, JobEventType
from core.models import ComputeResource, Job, JobEvent, Program, Provider
from core.services.ray import JobHandler
from core.utils import check_logs


class TestCommands(APITestCase):
    """Tests for commands."""

    fixtures = ["tests/fixtures/schedule_fixtures.json"]

    def test_create_compute_resource(self):
        """Tests compute resource creation command."""
        call_command("create_compute_resource", "test_host")
        resources = ComputeResource.objects.all()
        self.assertTrue(
            "Ray cluster default" in [resource.title for resource in resources]
        )

    def test_free_resources(self):
        """Tests free resources command."""
        call_command("free_resources")
        num_resources = ComputeResource.objects.count()
        self.assertEqual(num_resources, 1)

    @patch("scheduler.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_jobs_statuses(self, get_job_handler):
        """Tests update of job statuses."""
        # Test status change from PENDING to RUNNING
        ray_client = MagicMock()
        ray_client.get_job_status.return_value = JobStatus.RUNNING
        ray_client.get_job_logs.return_value = "No logs yet."
        ray_client.stop_job.return_value = True
        ray_client.submit_job.return_value = "AwesomeJobId"
        get_job_handler.return_value = JobHandler(ray_client)

        job = self._create_test_job(ray_job_id="test_update_jobs_statuses")

        call_command("update_jobs_statuses")

        job.refresh_from_db()
        self.assertEqual(job.status, "RUNNING")
        self.assertEqual(job.logs, "No logs yet.")
        self.assertIsNotNone(job.env_vars)

        job_events = JobEvent.objects.filter(job=job)
        self.assertEqual(len(job_events), 1)
        self.assertEqual(job_events[0].event_type, JobEventType.STATUS_CHANGE)
        self.assertEqual(job_events[0].data["status"], JobStatus.RUNNING)
        self.assertEqual(job_events[0].data["sub_status"], None)
        self.assertEqual(job_events[0].origin, JobEventOrigin.SCHEDULER)
        self.assertEqual(job_events[0].context, JobEventContext.UPDATE_JOB_STATUS)

        # Test job logs for FAILED job with empty logs
        ray_client.get_job_status.return_value = JobStatus.FAILED
        ray_client.get_job_logs.return_value = ""

        call_command("update_jobs_statuses")

        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertEqual(job.logs, f"Job {job.id} failed due to an internal error.")
        self.assertEqual(job.env_vars, "{}")
        self.assertIsNone(job.sub_status)

        job_events = JobEvent.objects.filter(job=job).order_by("created")
        self.assertEqual(len(job_events), 2)
        self.assertEqual(job_events[1].event_type, JobEventType.STATUS_CHANGE)
        self.assertEqual(job_events[1].data["status"], JobStatus.FAILED)
        self.assertEqual(job_events[1].data["sub_status"], None)
        self.assertEqual(job_events[1].origin, JobEventOrigin.SCHEDULER)
        self.assertEqual(job_events[1].context, JobEventContext.UPDATE_JOB_STATUS)

    @patch("scheduler.management.commands.schedule_queued_jobs.execute_job")
    def test_schedule_queued_jobs(self, execute_job):
        """Tests schedule of queued jobs command."""
        fake_job = MagicMock()
        fake_job.id = "1a7947f9-6ae8-4e3d-ac1e-e7d608deec82"
        fake_job.logs = ""
        fake_job.status = "SUCCEEDED"
        fake_job.sub_status = None
        fake_job.program.artifact.path = "non_existing_file.tar"
        fake_job.save.return_value = None

        execute_job.return_value = fake_job
        call_command("schedule_queued_jobs")
        # TODO: mock execute job to change status of job and query for QUEUED jobs  # pylint: disable=fixme
        job_count = Job.objects.count()
        self.assertEqual(job_count, 7)

        job_events = JobEvent.objects.filter(job_id=fake_job.id)
        # There is one Job in the fixtures in QUEUED state. It call execute_job twice
        # and add 2 equal events. If we remove fixtures we can fix this test properly
        self.assertEqual(len(job_events), 2)
        self.assertEqual(job_events[0].event_type, JobEventType.STATUS_CHANGE)
        self.assertEqual(job_events[0].data["status"], JobStatus.SUCCEEDED)
        self.assertEqual(job_events[0].data["sub_status"], None)
        self.assertEqual(job_events[0].origin, JobEventOrigin.SCHEDULER)
        self.assertEqual(job_events[0].context, JobEventContext.SCHEDULE_JOBS)
        self.assertEqual(job_events[1].event_type, JobEventType.STATUS_CHANGE)
        self.assertEqual(job_events[1].data["status"], JobStatus.SUCCEEDED)
        self.assertEqual(job_events[1].data["sub_status"], None)
        self.assertEqual(job_events[1].origin, JobEventOrigin.SCHEDULER)
        self.assertEqual(job_events[1].context, JobEventContext.SCHEDULE_JOBS)

    def test_check_empty_logs(self):
        """Test error notification for failed and empty logs."""
        job = MagicMock()
        job.id = "42"
        job.status = "FAILED"
        logs = check_logs(logs="", job=job)
        self.assertEqual(logs, "Job 42 failed due to an internal error.")

    def test_check_non_empty_logs(self):
        """Test logs checker for non empty logs."""
        job = MagicMock()
        job.id = "42"
        job.status = "FAILED"
        logs = check_logs(logs="awsome logs", job=job)
        self.assertEqual(logs, "awsome logs")

    def test_check_long_logs(self):
        """Test logs checker for very long logs in this case more than 1MB."""

        with self.settings(
            FUNCTIONS_LOGS_SIZE_LIMIT=100,
        ):
            job = MagicMock()
            job.id = "42"
            job.status = "RUNNING"
            log_to_test = "A" * 120 + "B"
            logs = check_logs(logs=log_to_test, job=job)
            self.assertIn(
                "[Logs exceeded maximum allowed size (9.5367431640625e-05 MB). Logs have been truncated, discarding the oldest entries first.]",
                logs,
            )
            self.assertIn(
                "AAAAAAAAAAB",
                logs,
            )

    def _create_test_job(
        self,
        author: str = "test_author",
        provider_admin: Optional[str] = None,
        status: str = Job.PENDING,
        compute_resource: Optional[ComputeResource] = None,
        ray_job_id: str = "test-job-id",
        gpu: bool = False,
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
            compute_resource = ComputeResource.objects.create(
                title=f"test-cluster-{ray_job_id}", active=True
            )

        author_user, _ = User.objects.get_or_create(username=author)
        provider = None

        if provider_admin:
            provider = Provider.objects.create(name=provider_admin)
            admin_group, _ = Group.objects.get_or_create(name=provider_admin)
            admin_user, _ = User.objects.get_or_create(username=provider_admin)
            admin_user.groups.add(admin_group)
            provider.admin_groups.add(admin_group)

        program = Program.objects.create(
            title=f"program-{author_user.username}-{provider_admin or 'custom'}",
            author=author_user,
            provider=provider,
        )

        return Job.objects.create(
            author=author_user,
            program=program,
            status=status,
            compute_resource=compute_resource,
            ray_job_id=ray_job_id,
            gpu=gpu,
        )
