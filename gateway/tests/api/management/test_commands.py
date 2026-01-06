"""Tests for commands."""

from datetime import datetime
from django.core.management import call_command
from ray.dashboard.modules.job.common import JobStatus
from rest_framework.test import APITestCase
from unittest.mock import patch, MagicMock

from api.domain.function import check_logs
from api.models import ComputeResource, Job
from api.ray import JobHandler


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

    @patch("api.ray.get_job_handler")
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

        # Test job logs for FAILED job with empty logs
        ray_client.get_job_status.return_value = JobStatus.FAILED
        ray_client.get_job_logs.return_value = ""

        call_command("update_jobs_statuses")

        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertEqual(job.logs, f"Job {job.id} failed due to an internal error.")
        self.assertEqual(job.env_vars, "{}")
        self.assertIsNone(job.sub_status)

    @patch("api.schedule.execute_job")
    def test_schedule_queued_jobs(self, execute_job):
        """Tests schedule of queued jobs command."""
        fake_job = MagicMock()
        fake_job.id = "1a7947f9-6ae8-4e3d-ac1e-e7d608deec82"
        fake_job.logs = ""
        fake_job.status = "SUCCEEDED"
        fake_job.program.artifact.path = "non_existing_file.tar"
        fake_job.save.return_value = None

        execute_job.return_value = fake_job
        call_command("schedule_queued_jobs")
        # TODO: mock execute job to change status of job and query for QUEUED jobs  # pylint: disable=fixme
        job_count = Job.objects.count()
        self.assertEqual(job_count, 7)

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
            FUNCTIONS_LOGS_SIZE_LIMIT="1",
        ):
            job = MagicMock()
            job.id = "42"
            job.status = "RUNNING"
            logs = check_logs(logs=("A" * (1_200_000)), job=job)
            self.assertIn(
                "Logs exceeded maximum allowed size (1 MB) and could not be stored.",
                logs,
            )

    def _create_test_job(self, ray_job_id="test-job-id", status=None):
        """Helper method to create a test job with fresh state."""
        # Get existing job to use its relationships and set it to STOPPED
        existing_job = Job.objects.get(id__exact="1a7947f9-6ae8-4e3d-ac1e-e7d608deec84")
        existing_job.status = Job.STOPPED
        existing_job.save()

        # Create a new job for testing
        job = Job.objects.create(
            author=existing_job.author,
            program=existing_job.program,
            compute_resource=existing_job.compute_resource,
            env_vars="{'foo':'bar'}",
            status=Job.PENDING,
            created=datetime.now(),
            ray_job_id=ray_job_id,
        )
        return job
