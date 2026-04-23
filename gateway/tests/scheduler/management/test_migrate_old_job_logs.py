"""Tests for migrate_old_job_logs command."""

import uuid
from typing import Optional

from django.contrib.auth.models import User, Group
from django.core.management import call_command
from rest_framework.test import APITestCase

from core.models import ComputeResource, Job, Program, Provider, Config
from core.services.storage.logs_storage import LogsStorage


class TestMigrateOldJobLogs(APITestCase):
    """Tests for migrate_old_job_logs command."""

    fixtures = ["tests/fixtures/schedule_fixtures.json"]

    def setUp(self):
        Config.add_defaults()

    def test_migrate_jobs_logs_to_storage_active(self):
        """Tests that logs are not migrated with an active compute resource."""

        with self.settings(JOB_LOGS_MIGRATION_BATCH_SIZE=10):
            compute_resource_active = ComputeResource.objects.create(title=f"test-cluster-migrate-logs", active=True)
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
            compute_resource_active = ComputeResource.objects.create(title=f"test-cluster-migrate-logs", active=True)
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
            self.assertEqual(job_succeeded_not_active_storage.get_public_logs(), test_logs)

            self.assertEqual(job_failed_not_active.logs, "")
            self.assertEqual(job_failed_not_active_storage.get_public_logs(), test_logs)

            self.assertEqual(job_stopped_not_active.logs, "")
            self.assertEqual(job_stopped_not_active_storage.get_public_logs(), test_logs)

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
            self.assertEqual(job_succeeded_not_active_storage.get_private_logs(), test_logs)

            self.assertEqual(job_failed_not_active.logs, "")
            self.assertEqual(job_failed_not_active_storage.get_public_logs(), None)
            self.assertEqual(job_failed_not_active_storage.get_private_logs(), test_logs)

            self.assertEqual(job_stopped_not_active.logs, "")
            self.assertEqual(job_stopped_not_active_storage.get_public_logs(), None)
            self.assertEqual(job_stopped_not_active_storage.get_private_logs(), test_logs)

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

    def test_migrate_jobs_logs_to_storage_max_jobs(self):
        """Tests that --max-jobs 1 only migrates a single job."""

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
                for _ in range(5)
            ]

            call_command("migrate_old_job_logs", max_jobs=1)

            empty_logs_count = 0
            for job in job_list:
                job.refresh_from_db()
                if job.logs == "":
                    empty_logs_count += 1

            self.assertEqual(empty_logs_count, 1)

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
        """Helper method to create a test job."""
        if compute_resource is None:
            compute_resource = ComputeResource.objects.create(title=f"test-cluster-{ray_job_id}", active=True)

        author_user, _ = User.objects.get_or_create(username=author)
        provider = None

        if provider_admin:
            provider = Provider.objects.create(name=provider_admin)
            admin_group, _ = Group.objects.get_or_create(name=provider_admin)
            admin_user, _ = User.objects.get_or_create(username=provider_admin)
            admin_user.groups.add(admin_group)
            provider.admin_groups.add(admin_group)

        program = Program.objects.create(
            title=f"program-{author_user.username}-{provider_admin or uuid.uuid4().hex[:8]}",
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
