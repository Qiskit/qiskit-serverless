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

    @patch("api.management.commands.update_jobs_statuses.get_job_handler")
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

    @patch("api.schedule.kill_ray_cluster")
    @patch("api.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_jobs_statuses_handler_returns_none(
        self, get_job_handler, kill_ray_cluster
    ):
        """Test update_jobs_statuses when get_job_handler returns None."""
        get_job_handler.return_value = None
        kill_ray_cluster.return_value = True

        job = self._create_test_job(ray_job_id="test-handler-none")
        try:
            call_command("update_jobs_statuses")

            # Job should be handled by handle_job_status_not_available
            job.refresh_from_db()
            # The job status handling depends on handle_job_status_not_available implementation
            # but the command should not crash
            self.assertIsNotNone(job.status)
            # Assert compute_resource was deleted (handle_job_status_not_available behavior)
            self.assertIsNone(job.compute_resource)
            # Assert job status was updated to FAILED
            self.assertEqual(job.status, "FAILED")
        finally:
            if Job.objects.filter(id=job.id).exists():
                job.delete()

    @patch("api.schedule.kill_ray_cluster")
    @patch("api.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_jobs_statuses_handler_raises_exception(
        self, get_job_handler, kill_ray_cluster
    ):
        """Test update_jobs_statuses when get_job_handler raises exception."""
        get_job_handler.side_effect = Exception("Connection error")
        kill_ray_cluster.return_value = True

        job = self._create_test_job(ray_job_id="test-handler-exception")
        try:
            call_command("update_jobs_statuses")

            # Job should be handled by handle_job_status_not_available
            job.refresh_from_db()
            self.assertIsNotNone(job.status)
            # Assert compute_resource was deleted (handle_job_status_not_available behavior)
            self.assertIsNone(job.compute_resource)
            # Assert job status was updated to FAILED
            self.assertEqual(job.status, "FAILED")
        finally:
            if Job.objects.filter(id=job.id).exists():
                job.delete()

    @patch("api.schedule.kill_ray_cluster")
    @patch("api.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_jobs_statuses_status_raises_exception(
        self, get_job_handler, kill_ray_cluster
    ):
        """Test update_jobs_statuses when job_handler.status() raises exception."""
        ray_client = MagicMock()
        ray_client.get_job_status.side_effect = Exception("Ray API error")
        # Configure logs to not raise exception
        ray_client.get_job_logs.return_value = "Some logs despite status error"
        get_job_handler.return_value = JobHandler(ray_client)
        kill_ray_cluster.return_value = True

        job = self._create_test_job(ray_job_id="test-status-exception")
        try:
            call_command("update_jobs_statuses")

            # Job should be handled by handle_job_status_not_available
            # but logs should still be attempted since job_handler is valid
            job.refresh_from_db()
            self.assertIsNotNone(job.status)
            # Assert job_handler was created (not None)
            self.assertIsNotNone(get_job_handler.return_value)
            # Assert compute_resource was deleted
            self.assertIsNone(job.compute_resource)
            # Assert job status was updated to FAILED
            self.assertEqual(job.status, "FAILED")
        finally:
            if Job.objects.filter(id=job.id).exists():
                job.delete()

    @patch("api.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_jobs_statuses_logs_raises_exception(self, get_job_handler):
        """Test update_jobs_statuses when job_handler.logs() raises exception."""
        ray_client = MagicMock()
        ray_client.get_job_status.return_value = JobStatus.RUNNING
        ray_client.get_job_logs.side_effect = Exception("Logs API error")
        get_job_handler.return_value = JobHandler(ray_client)

        job = self._create_test_job(ray_job_id="test-logs-exception")
        initial_status = job.status
        try:
            call_command("update_jobs_statuses")
            # Status should be updated but logs should not crash the command
            job.refresh_from_db()
            # Assert status changed from PENDING to RUNNING
            self.assertNotEqual(job.status, initial_status)
            self.assertEqual(job.status, "RUNNING")
        finally:
            job.delete()

    @patch("api.schedule.kill_ray_cluster")
    @patch("api.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_jobs_statuses_kill_cluster_fails(
        self, get_job_handler, kill_ray_cluster
    ):
        """Test update_jobs_statuses when kill_ray_cluster fails."""
        # Configure get_job_handler to return None (which triggers handle_job_status_not_available)
        get_job_handler.return_value = None
        # Configure kill_ray_cluster to raise an exception
        kill_ray_cluster.side_effect = Exception("Kubernetes API error")

        job = self._create_test_job(ray_job_id="test-kill-cluster-fail")
        compute_resource = job.compute_resource
        try:
            # Command should not crash even if kill_ray_cluster fails
            call_command("update_jobs_statuses")

            # Job should still be processed despite kill_ray_cluster failure
            job.refresh_from_db()
            # Assert job status was updated to FAILED
            self.assertEqual(job.status, "FAILED")
            # Assert compute_resource was deleted from DB despite kill failure
            self.assertIsNone(job.compute_resource)
            # Assert the compute resource no longer exists in DB

            self.assertFalse(
                ComputeResource.objects.filter(id=compute_resource.id).exists()
            )
            # Assert kill_ray_cluster was called
            kill_ray_cluster.assert_called_once()
        finally:
            # Clean up if job still exists
            if Job.objects.filter(id=job.id).exists():
                job.delete()

    @patch("api.schedule.kill_ray_cluster")
    @patch("api.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_jobs_statuses_insufficient_resources_kill_fails(
        self, get_job_handler, kill_ray_cluster
    ):
        """Test update_jobs_statuses with insufficient resources when kill_ray_cluster fails."""
        # Configure job handler to return logs indicating insufficient resources
        ray_client = MagicMock()
        ray_client.get_job_status.return_value = JobStatus.RUNNING
        ray_client.get_job_logs.return_value = (
            "No available node types can fulfill resource request"
        )
        get_job_handler.return_value = JobHandler(ray_client)

        # Configure kill_ray_cluster to raise an exception
        kill_ray_cluster.side_effect = Exception("Kubernetes API error")

        job = self._create_test_job(ray_job_id="test-insufficient-resources-kill-fail")
        compute_resource = job.compute_resource
        try:
            # Command should not crash even if kill_ray_cluster fails
            call_command("update_jobs_statuses")

            # Job should still be processed despite kill_ray_cluster failure
            job.refresh_from_db()
            # Assert job status was updated to FAILED
            self.assertEqual(job.status, "FAILED")
            # Assert compute_resource was deleted from DB despite kill failure
            self.assertIsNone(job.compute_resource)
            # Assert the compute resource no longer exists in DB

            self.assertFalse(
                ComputeResource.objects.filter(id=compute_resource.id).exists()
            )
            # Assert logs contain insufficient resources message
            self.assertIn("Insufficient resources", job.logs)
            # Assert kill_ray_cluster was called
            kill_ray_cluster.assert_called_once()
        finally:
            # Clean up if job still exists
            if Job.objects.filter(id=job.id).exists():
                job.delete()

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
