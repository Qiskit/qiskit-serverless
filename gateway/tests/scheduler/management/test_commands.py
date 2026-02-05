"""Tests for commands."""

import os
import tempfile
from typing import Optional

from django.contrib.auth.models import User, Group
from django.core.management import call_command
from ray.dashboard.modules.job.common import JobStatus
from rest_framework.test import APITestCase
from unittest.mock import patch, MagicMock

from api.domain.function import check_logs
from api.models import ComputeResource, Job, Program, Provider
from api.services.storage.logs_storage import LogsStorage
from core.services.ray import JobHandler


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
        self.assertIsNotNone(job.env_vars)

        # Test job logs for FAILED job with empty logs
        ray_client.get_job_status.return_value = JobStatus.FAILED
        ray_client.get_job_logs.return_value = ""

        call_command("update_jobs_statuses")

        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertEqual(job.env_vars, "{}")
        self.assertIsNone(job.sub_status)

    @patch("scheduler.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_jobs_statuses_job_not_found_in_ray(self, get_job_handler):
        """Tests that job is marked as FAILED when it no longer exists in Ray."""
        job_handler = MagicMock()
        job_handler.status.side_effect = RuntimeError(
            "Request failed with status code 404: Job raysubmit_xyz does not exist."
        )
        get_job_handler.return_value = job_handler

        job = self._create_test_job(ray_job_id="test_job_not_found")

        call_command("update_jobs_statuses")

        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertEqual(job.env_vars, "{}")
        self.assertIsNone(job.sub_status)

    @patch("scheduler.management.commands.schedule_queued_jobs.execute_job")
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

    @patch("scheduler.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_jobs_statuses_filters_logs_user_function(self, get_job_handler):
        """Tests that logs are filtered when saving for function without provider."""
        compute_resource = ComputeResource.objects.create(
            title="test-cluster-user-logs", active=True
        )
        job = self._create_test_job(
            author="test_author",
            status=Job.RUNNING,
            compute_resource=compute_resource,
            ray_job_id="test-ray-job-id",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.settings(MEDIA_ROOT=temp_dir, RAY_CLUSTER_MODE={"local": True}):
                # Mock Ray to return unfiltered logs with PUBLIC and PRIVATE markers
                full_logs = """
2026-01-06 10:00:00,000 INFO job_manager.py:568 -- Runtime env is setting up.

[PUBLIC] INFO: Public user log
[PRIVATE] INFO: Private provider log
[PUBLIC] INFO: Another public log
Ray internal log without marker
[PUBLIC] INFO: Final public log
"""

                ray_client = MagicMock()
                ray_client.get_job_status.return_value = JobStatus.SUCCEEDED
                ray_client.get_job_logs.return_value = full_logs
                get_job_handler.return_value = JobHandler(ray_client)

                call_command("update_jobs_statuses")

                # User logs are located in username/logs/
                # Verify user logs are filtered: [PUBLIC] only lines without the [PUBLIC]
                user_log_file_path = os.path.join(
                    temp_dir,
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
                self.assertEqual(saved_user_logs, expected_user_logs)

                private_log_file_path = os.path.join(
                    temp_dir,
                    "program-test_author-custom",
                    "logs",
                    f"{job.id}.log",
                )
                # private log shouldn't exist
                self.assertFalse(os.path.exists(private_log_file_path))

                job.refresh_from_db()
                self.assertTrue(job.logs == "")

    @patch("scheduler.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_jobs_statuses_filters_logs_provider_function(self, get_job_handler):
        """Tests that logs are filtered when saving for function with provider."""
        compute_resource = ComputeResource.objects.create(
            title="test-cluster-provider-logs", active=True
        )
        job = self._create_test_job(
            author="test_author",
            provider_admin="test_provider",
            status=Job.RUNNING,
            compute_resource=compute_resource,
            ray_job_id="test-ray-job-id-with-provider",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.settings(MEDIA_ROOT=temp_dir, RAY_CLUSTER_MODE={"local": True}):
                # Mock Ray to return unfiltered logs
                full_logs = """
[PUBLIC] INFO: Public log for user

[PRIVATE] INFO: Private log for provider only
[PUBLIC] INFO: Another public log
Internal system log
[PRIVATE] WARNING: Private warning
[PUBLIC] INFO: Final public log
"""

                ray_client = MagicMock()
                ray_client.get_job_status.return_value = JobStatus.SUCCEEDED
                ray_client.get_job_logs.return_value = full_logs
                get_job_handler.return_value = JobHandler(ray_client)

                call_command("update_jobs_statuses")

                # User logs are located in username/provider/function/logs/ for provider jobs
                # Verify user logs are filtered: [PUBLIC] only lines without the [PUBLIC]
                user_log_file_path = os.path.join(
                    temp_dir,
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
                self.assertEqual(saved_user_logs, expected_user_logs)

                # Verify provider logs contain everything: [PUBLIC], [PRIVATE] and internal logs...
                provider_log_file_path = os.path.join(
                    temp_dir,
                    "test_provider",
                    "program-test_author-test_provider",
                    "logs",
                    f"{job.id}.log",
                )

                with open(provider_log_file_path, "r", encoding="utf-8") as log_file:
                    saved_provider_logs = log_file.read()
                self.assertEqual(saved_provider_logs, expected_provider_logs)

    def test_migrate_jobs_logs_to_storage_active(self):
        """Tests that logs are not migrated with an active compute resource."""

        with self.settings(JOB_LOGS_MIGRATION_BATCH_SIZE=10):
            compute_resource_active = ComputeResource.objects.create(
                title=f"test-cluster-migrate-logs", active=True
            )
            test_logs = "This is a log for testing pourposes"

            job_succeeded_active = self._create_test_job(
                status=Job.SUCCEEDED,
                compute_resource=compute_resource_active,
                logs=test_logs,
            )
            job_failed_active = self._create_test_job(
                status=Job.FAILED,
                compute_resource=compute_resource_active,
                logs=test_logs,
            )
            job_stopped_active = self._create_test_job(
                status=Job.STOPPED,
                compute_resource=compute_resource_active,
                logs=test_logs,
            )
            job_queued_active = self._create_test_job(
                status=Job.QUEUED,
                compute_resource=compute_resource_active,
                logs=test_logs,
            )
            job_running_active = self._create_test_job(
                status=Job.RUNNING,
                compute_resource=compute_resource_active,
                logs=test_logs,
            )

            call_command("migrate_old_job_logs")

            job_succeeded_active.refresh_from_db()
            job_succeeded_active_storage = LogsStorage(job_succeeded_active)
            job_failed_active.refresh_from_db()
            job_failed_active_storage = LogsStorage(job_failed_active)
            job_stopped_active.refresh_from_db()
            job_stopped_active_storage = LogsStorage(job_stopped_active)
            job_queued_active.refresh_from_db()
            job_queued_active_storage = LogsStorage(job_queued_active)
            job_running_active.refresh_from_db()
            job_running_active_storage = LogsStorage(job_running_active)

            self.assertEqual(job_succeeded_active.logs, test_logs)
            self.assertEqual(job_succeeded_active_storage.get_public_logs(), None)

            self.assertEqual(job_failed_active.logs, test_logs)
            self.assertEqual(job_failed_active_storage.get_public_logs(), None)

            self.assertEqual(job_stopped_active.logs, test_logs)
            self.assertEqual(job_stopped_active_storage.get_public_logs(), None)

            self.assertEqual(job_queued_active.logs, test_logs)
            self.assertEqual(job_queued_active_storage.get_public_logs(), None)

            self.assertEqual(job_running_active.logs, test_logs)
            self.assertEqual(job_running_active_storage.get_public_logs(), None)

    def test_migrate_jobs_logs_to_storage_active_with_provider(self):
        """Tests that logs are not migrated with an active compute resource belonging a provider function."""

        with self.settings(JOB_LOGS_MIGRATION_BATCH_SIZE=10):
            compute_resource_active = ComputeResource.objects.create(
                title=f"test-cluster-migrate-logs", active=True
            )
            test_logs = "This is a log for testing pourposes"

            job_succeeded_active = self._create_test_job(
                status=Job.SUCCEEDED,
                compute_resource=compute_resource_active,
                logs=test_logs,
                provider_admin="test_provider_1",
            )
            job_failed_active = self._create_test_job(
                status=Job.FAILED,
                compute_resource=compute_resource_active,
                logs=test_logs,
                provider_admin="test_provider_2",
            )
            job_stopped_active = self._create_test_job(
                status=Job.STOPPED,
                compute_resource=compute_resource_active,
                logs=test_logs,
                provider_admin="test_provider_3",
            )
            job_queued_active = self._create_test_job(
                status=Job.QUEUED,
                compute_resource=compute_resource_active,
                logs=test_logs,
                provider_admin="test_provider_4",
            )
            job_running_active = self._create_test_job(
                status=Job.RUNNING,
                compute_resource=compute_resource_active,
                logs=test_logs,
                provider_admin="test_provider_5",
            )

            call_command("migrate_old_job_logs")

            job_succeeded_active.refresh_from_db()
            job_succeeded_active_storage = LogsStorage(job_succeeded_active)
            job_failed_active.refresh_from_db()
            job_failed_active_storage = LogsStorage(job_failed_active)
            job_stopped_active.refresh_from_db()
            job_stopped_active_storage = LogsStorage(job_stopped_active)
            job_queued_active.refresh_from_db()
            job_queued_active_storage = LogsStorage(job_queued_active)
            job_running_active.refresh_from_db()
            job_running_active_storage = LogsStorage(job_running_active)

            self.assertEqual(job_succeeded_active.logs, test_logs)
            self.assertEqual(job_succeeded_active_storage.get_public_logs(), None)
            self.assertEqual(job_succeeded_active_storage.get_private_logs(), None)

            self.assertEqual(job_failed_active.logs, test_logs)
            self.assertEqual(job_failed_active_storage.get_public_logs(), None)
            self.assertEqual(job_failed_active_storage.get_private_logs(), None)

            self.assertEqual(job_stopped_active.logs, test_logs)
            self.assertEqual(job_stopped_active_storage.get_public_logs(), None)
            self.assertEqual(job_stopped_active_storage.get_private_logs(), None)

            self.assertEqual(job_queued_active.logs, test_logs)
            self.assertEqual(job_queued_active_storage.get_public_logs(), None)
            self.assertEqual(job_queued_active_storage.get_private_logs(), None)

            self.assertEqual(job_running_active.logs, test_logs)
            self.assertEqual(job_running_active_storage.get_public_logs(), None)
            self.assertEqual(job_running_active_storage.get_private_logs(), None)

    def test_migrate_jobs_logs_to_storage_not_active(self):
        """Tests that logs are properly migrated with a not active compute resource."""

        with self.settings(JOB_LOGS_MIGRATION_BATCH_SIZE=10):
            compute_resource_not_active = ComputeResource.objects.create(
                title=f"test-cluster-migrate-logs", active=False
            )
            test_logs = "This is a log for testing pourposes"

            job_succeeded_not_active = self._create_test_job(
                status=Job.SUCCEEDED,
                compute_resource=compute_resource_not_active,
                logs=test_logs,
            )
            job_failed_not_active = self._create_test_job(
                status=Job.FAILED,
                compute_resource=compute_resource_not_active,
                logs=test_logs,
            )
            job_stopped_not_active = self._create_test_job(
                status=Job.STOPPED,
                compute_resource=compute_resource_not_active,
                logs=test_logs,
            )
            job_queued_not_active = self._create_test_job(
                status=Job.QUEUED,
                compute_resource=compute_resource_not_active,
                logs=test_logs,
            )
            job_running_not_active = self._create_test_job(
                status=Job.RUNNING,
                compute_resource=compute_resource_not_active,
                logs=test_logs,
            )

            call_command("migrate_old_job_logs")

            job_succeeded_not_active.refresh_from_db()
            job_succeeded_not_active_storage = LogsStorage(job_succeeded_not_active)
            job_failed_not_active.refresh_from_db()
            job_failed_not_active_storage = LogsStorage(job_failed_not_active)
            job_stopped_not_active.refresh_from_db()
            job_stopped_not_active_storage = LogsStorage(job_stopped_not_active)
            job_queued_not_active.refresh_from_db()
            job_queued_not_active_storage = LogsStorage(job_queued_not_active)
            job_running_not_active.refresh_from_db()
            job_running_not_active_storage = LogsStorage(job_running_not_active)

            self.assertEqual(job_succeeded_not_active.logs, "")
            self.assertEqual(
                job_succeeded_not_active_storage.get_public_logs(), test_logs
            )

            self.assertEqual(job_failed_not_active.logs, "")
            self.assertEqual(job_failed_not_active_storage.get_public_logs(), test_logs)

            self.assertEqual(job_stopped_not_active.logs, "")
            self.assertEqual(
                job_stopped_not_active_storage.get_public_logs(), test_logs
            )

            self.assertEqual(job_queued_not_active.logs, test_logs)
            self.assertEqual(job_queued_not_active_storage.get_public_logs(), None)

            self.assertEqual(job_running_not_active.logs, test_logs)
            self.assertEqual(job_running_not_active_storage.get_public_logs(), None)

    def test_migrate_jobs_logs_to_storage_not_active_with_provider(self):
        """Tests that logs are properly migrated with a not active compute resource belonging a provider function."""

        with self.settings(JOB_LOGS_MIGRATION_BATCH_SIZE=10):
            compute_resource_not_active = ComputeResource.objects.create(
                title=f"test-cluster-migrate-logs", active=False
            )
            test_logs = "This is a log for testing pourposes"

            job_succeeded_not_active = self._create_test_job(
                status=Job.SUCCEEDED,
                compute_resource=compute_resource_not_active,
                logs=test_logs,
                provider_admin="test_provider_1",
            )
            job_failed_not_active = self._create_test_job(
                status=Job.FAILED,
                compute_resource=compute_resource_not_active,
                logs=test_logs,
                provider_admin="test_provider_2",
            )
            job_stopped_not_active = self._create_test_job(
                status=Job.STOPPED,
                compute_resource=compute_resource_not_active,
                logs=test_logs,
                provider_admin="test_provider_3",
            )
            job_queued_not_active = self._create_test_job(
                status=Job.QUEUED,
                compute_resource=compute_resource_not_active,
                logs=test_logs,
                provider_admin="test_provider_4",
            )
            job_running_not_active = self._create_test_job(
                status=Job.RUNNING,
                compute_resource=compute_resource_not_active,
                logs=test_logs,
                provider_admin="test_provider_5",
            )

            call_command("migrate_old_job_logs")

            job_succeeded_not_active.refresh_from_db()
            job_succeeded_not_active_storage = LogsStorage(job_succeeded_not_active)
            job_failed_not_active.refresh_from_db()
            job_failed_not_active_storage = LogsStorage(job_failed_not_active)
            job_stopped_not_active.refresh_from_db()
            job_stopped_not_active_storage = LogsStorage(job_stopped_not_active)
            job_queued_not_active.refresh_from_db()
            job_queued_not_active_storage = LogsStorage(job_queued_not_active)
            job_running_not_active.refresh_from_db()
            job_running_not_active_storage = LogsStorage(job_running_not_active)

            self.assertEqual(job_succeeded_not_active.logs, "")
            self.assertEqual(job_succeeded_not_active_storage.get_public_logs(), None)
            self.assertEqual(
                job_succeeded_not_active_storage.get_private_logs(), test_logs
            )

            self.assertEqual(job_failed_not_active.logs, "")
            self.assertEqual(job_failed_not_active_storage.get_public_logs(), None)
            self.assertEqual(
                job_failed_not_active_storage.get_private_logs(), test_logs
            )

            self.assertEqual(job_stopped_not_active.logs, "")
            self.assertEqual(job_stopped_not_active_storage.get_public_logs(), None)
            self.assertEqual(
                job_stopped_not_active_storage.get_private_logs(), test_logs
            )

            self.assertEqual(job_queued_not_active.logs, test_logs)
            self.assertEqual(job_queued_not_active_storage.get_public_logs(), None)
            self.assertEqual(job_queued_not_active_storage.get_private_logs(), None)

            self.assertEqual(job_running_not_active.logs, test_logs)
            self.assertEqual(job_running_not_active_storage.get_public_logs(), None)
            self.assertEqual(job_running_not_active_storage.get_private_logs(), None)

    def test_migrate_jobs_logs_to_storage_too_much_elements(self):
        """Tests that logs are properly migrated in batches of JOB_LOGS_MIGRATION_BATCH_SIZE."""

        with self.settings(JOB_LOGS_MIGRATION_BATCH_SIZE=10):
            compute_resource_not_active = ComputeResource.objects.create(
                title=f"test-cluster-migrate-logs", active=False
            )
            test_logs = "This is a log for testing pourposes"

            job_list = [
                self._create_test_job(
                    status=Job.SUCCEEDED,
                    compute_resource=compute_resource_not_active,
                    logs=test_logs,
                )
                for _ in range(15)
            ]

            call_command("migrate_old_job_logs")

            empty_logs_count = 0
            for job in job_list:
                job.refresh_from_db()
                if job.logs == "":
                    empty_logs_count += 1

            self.assertEqual(empty_logs_count, 15)

    def _create_test_job(
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
            logs=logs,
        )
