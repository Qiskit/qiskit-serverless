"""Tests for commands."""

import os
import tempfile
from datetime import datetime
from django.core.management import call_command
from ray.dashboard.modules.job.common import JobStatus
from rest_framework.test import APITestCase
from unittest.mock import Mock, patch, MagicMock

from api.domain.function import check_logs
from api.models import ComputeResource, Job, Program, Provider
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
        self.assertIsNotNone(job.env_vars)

        # Test job logs for FAILED job with empty logs
        ray_client.get_job_status.return_value = JobStatus.FAILED
        ray_client.get_job_logs.return_value = ""

        call_command("update_jobs_statuses")

        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
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

    @patch("api.management.commands.free_resources.get_job_handler")
    def test_free_resources_filters_logs_user_function(self, get_job_handler):
        """Tests that logs are filtered when saving for function without provider."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.settings(MEDIA_ROOT=temp_dir, RAY_CLUSTER_MODE={"local": True}):
                # Create test data
                program = Program.objects.get(pk="1a7947f9-6ae8-4e3d-ac1e-e7d608deec82")
                compute_resource = ComputeResource.objects.get(
                    pk="1a7947f9-6ae8-4e3d-ac1e-e7d608deec99"
                )

                job = Job.objects.create(
                    author_id=1,
                    program=program,
                    compute_resource=compute_resource,
                    status=Job.SUCCEEDED,
                    ray_job_id="test-ray-job-id",
                    created=datetime.now(),
                )

                # Mock Ray to return unfiltered logs with PUBLIC and PRIVATE markers
                full_logs = """
2026-01-06 10:00:00,000 INFO job_manager.py:568 -- Runtime env is setting up.

[PUBLIC] INFO:user: Public user log
[PRIVATE] INFO:provider: Private provider log
[PUBLIC] INFO:user: Another public log
Ray internal log without marker
[PUBLIC] INFO:user: Final public log
"""

                ray_client = MagicMock()
                ray_client.get_job_logs.return_value = full_logs
                get_job_handler.return_value = JobHandler(ray_client)

                call_command("free_resources")

                # User logs are located in username/logs/
                # Verify user logs are filtered: [PUBLIC] only lines without the [PUBLIC]
                user_log_file_path = os.path.join(
                    temp_dir,
                    "test_user",
                    "logs",
                    f"{job.id}.log",
                )
                expected_user_logs = """
2026-01-06 10:00:00,000 INFO job_manager.py:568 -- Runtime env is setting up.

INFO:user: Public user log
INFO:provider: Private provider log
INFO:user: Another public log
Ray internal log without marker
INFO:user: Final public log
"""

                with open(user_log_file_path, "r", encoding="utf-8") as log_file:
                    saved_user_logs = log_file.read()
                self.assertEqual(saved_user_logs, expected_user_logs)

                private_log_file_path = os.path.join(
                    temp_dir,
                    program.title,
                    "logs",
                    f"{job.id}.log",
                )
                # private log shouldn't exist
                self.assertFalse(os.path.exists(private_log_file_path))

    @patch("api.management.commands.free_resources.get_job_handler")
    def test_free_resources_filters_logs_provider_function(self, get_job_handler):
        """Tests that logs are filtered when saving for function with provider."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.settings(MEDIA_ROOT=temp_dir, RAY_CLUSTER_MODE={"local": True}):
                # Create provider and program with provider
                provider = Provider.objects.create(
                    name="test-provider",
                    registry="docker.io/test",
                )

                program = Program.objects.create(
                    title="test-program-with-provider",
                    author_id=1,
                    provider=provider,
                    created=datetime.now(),
                )

                compute_resource = ComputeResource.objects.get(
                    pk="1a7947f9-6ae8-4e3d-ac1e-e7d608deec99"
                )

                job = Job.objects.create(
                    author_id=1,
                    program=program,
                    compute_resource=compute_resource,
                    status=Job.SUCCEEDED,
                    ray_job_id="test-ray-job-id-with-provider",
                    created=datetime.now(),
                )

                # Mock Ray to return unfiltered logs
                full_logs = """
[PUBLIC] INFO:user: Public log for user

[PRIVATE] INFO:provider: Private log for provider only
[PUBLIC] INFO:user: Another public log
Internal system log
[PRIVATE] WARNING:provider: Private warning
[PUBLIC] INFO:user: Final public log
"""

                ray_client = MagicMock()
                ray_client.get_job_logs.return_value = full_logs
                get_job_handler.return_value = JobHandler(ray_client)

                # Execute free_resources command
                call_command("free_resources")

                # User logs are located in username/provider/function/logs/ for provider jobs
                # Verify user logs are filtered: [PUBLIC] only lines without the [PUBLIC]
                user_log_file_path = os.path.join(
                    temp_dir,
                    "test_user",
                    provider.name,
                    program.title,
                    "logs",
                    f"{job.id}.log",
                )
                expected_user_logs = """INFO:user: Public log for user
INFO:user: Another public log
INFO:user: Final public log
"""

                with open(user_log_file_path, "r", encoding="utf-8") as log_file:
                    saved_user_logs = log_file.read()
                self.assertEqual(saved_user_logs, expected_user_logs)

                # Verify provider logs contain everything: [PUBLIC], [PRIVATE] and internal logs...
                provider_log_file_path = os.path.join(
                    temp_dir,
                    "test-provider",
                    "test-program-with-provider",
                    "logs",
                    f"{job.id}.log",
                )

                with open(provider_log_file_path, "r", encoding="utf-8") as log_file:
                    saved_provider_logs = log_file.read()
                self.assertEqual(saved_provider_logs, full_logs)

    @patch("api.management.commands.free_resources.get_job_handler", side_effect=ConnectionError())
    def test_free_resources_with_gpu_clusters_limits_zero(self, _):
        """Tests that logs are filtered when saving for function with provider."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.settings(
                MEDIA_ROOT=temp_dir,
                RAY_CLUSTER_MODE={"local": False},
                LIMITS_GPU_CLUSTERS=0,
            ):
                program = Program.objects.create(
                    title="test-program", author_id=1, created=datetime.now()
                )

                compute_resource = ComputeResource.objects.get(
                    pk="1a7947f9-6ae8-4e3d-ac1e-e7d608deec99"
                )

                job = Job.objects.create(
                    author_id=1,
                    program=program,
                    compute_resource=compute_resource,
                    status=Job.SUCCEEDED,
                    ray_job_id="test-ray-job-gpu",
                    created=datetime.now(),
                    gpu=True,
                )

                # Execute free_resources command
                call_command("free_resources")

                compute_resource = ComputeResource.objects.get(
                    pk="1a7947f9-6ae8-4e3d-ac1e-e7d608deec99"
                )

                self.assertTrue(compute_resource.active)

                # User logs are located in username/logs/
                # Verify user logs are filtered: [PUBLIC] only lines without the [PUBLIC]
                user_log_file_path = os.path.join(
                    temp_dir,
                    "test_user",
                    "logs",
                    f"{job.id}.log",
                )

                self.assertFalse(os.path.exists(user_log_file_path))

    @patch("api.management.commands.free_resources.get_job_handler", side_effect=ConnectionError())
    def test_free_resources_with_cpu_clusters_limits_zero(self, _):
        """Tests that logs are filtered when saving for function with provider."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.settings(
                MEDIA_ROOT=temp_dir,
                RAY_CLUSTER_MODE={"local": False},
                LIMITS_MAX_CLUSTERS=0,
            ):
                program = Program.objects.create(
                    title="test-program", author_id=1, created=datetime.now()
                )

                compute_resource = ComputeResource.objects.get(
                    pk="1a7947f9-6ae8-4e3d-ac1e-e7d608deec99"
                )

                job = Job.objects.create(
                    author_id=1,
                    program=program,
                    compute_resource=compute_resource,
                    status=Job.SUCCEEDED,
                    ray_job_id="test-ray-job-cpu",
                    created=datetime.now(),
                )

                # Execute free_resources command
                call_command("free_resources")

                compute_resource = ComputeResource.objects.get(
                    pk="1a7947f9-6ae8-4e3d-ac1e-e7d608deec99"
                )

                self.assertTrue(compute_resource.active)

                # User logs are located in username/logs/
                # Verify user logs are filtered: [PUBLIC] only lines without the [PUBLIC]
                user_log_file_path = os.path.join(
                    temp_dir,
                    "test_user",
                    "logs",
                    f"{job.id}.log",
                )

                self.assertFalse(os.path.exists(user_log_file_path))


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
