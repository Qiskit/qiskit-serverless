"""Tests for job logs APIs."""

import tempfile
from typing import Optional
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth.models import User, Group
from django.core.management import call_command
from django.urls import reverse
from ray.dashboard.modules.job.common import JobStatus
from rest_framework.status import HTTP_200_OK, HTTP_403_FORBIDDEN
from rest_framework.test import APITestCase, APIClient

from core.models import ComputeResource, Job, Program, Provider
from core.services.ray import JobHandler


def create_job(author: str, provider_admin: Optional[str] = None) -> Job:
    """Create a job for testing."""
    author_user, _ = User.objects.get_or_create(username=author)
    provider = None

    if provider_admin:
        provider = Provider.objects.create(name=provider_admin)
        admin_group, _ = Group.objects.get_or_create(name=provider_admin)
        admin_user, _ = User.objects.get_or_create(username=provider_admin)
        admin_user.groups.add(admin_group)
        provider.admin_groups.add(admin_group)

    program = Program.objects.create(
        title=f"{author_user}-{provider_admin or 'custom'}",
        author=author_user,
        provider=provider,
    )

    compute_resource = ComputeResource.objects.create(
        title="test-cluster-storage-provider-logs", active=True
    )

    return Job.objects.create(
        author=author_user,
        program=program,
        status="RUNNING",
        ray_job_id="test-ray-job-id",
        compute_resource=compute_resource,
    )


@pytest.mark.django_db
class TestJobLogsPermissions:
    """Permission tests for job logs endpoints."""

    @pytest.mark.parametrize(
        "endpoint,caller,provider_admin,expected_status",
        [
            # if provider is None, it means user jobs
            ("v1:jobs-logs", "author", None, HTTP_200_OK),
            ("v1:jobs-logs", "other_user", None, HTTP_403_FORBIDDEN),
            ("v1:jobs-logs", "author", "provider", HTTP_200_OK),
            ("v1:jobs-logs", "provider", "provider", HTTP_403_FORBIDDEN),
            ("v1:jobs-logs", "other_user", "provider", HTTP_403_FORBIDDEN),
            ("v1:jobs-provider-logs", "author", None, HTTP_403_FORBIDDEN),
            ("v1:jobs-provider-logs", "other_user", None, HTTP_403_FORBIDDEN),
            ("v1:jobs-provider-logs", "author", "provider", HTTP_403_FORBIDDEN),
            ("v1:jobs-provider-logs", "provider", "provider", HTTP_200_OK),
            ("v1:jobs-provider-logs", "other_user", "provider", HTTP_403_FORBIDDEN),
        ],
    )
    def test_endpoint_permissions(
        self, endpoint, caller, provider_admin, expected_status
    ):
        """Test permissions for /logs and /provider-logs endpoints."""
        user_caller, _ = User.objects.get_or_create(username=caller)
        job = create_job(author="author", provider_admin=provider_admin)

        client = APIClient()
        client.force_authenticate(user=user_caller)
        response = client.get(reverse(endpoint, args=[str(job.id)]), format="json")

        assert response.status_code == expected_status


class BaseJobLogsTest(APITestCase):
    """Base class for job logs tests with shared fixtures and helpers."""

    fixtures = ["tests/fixtures/fixtures.json"]

    def setUp(self):
        super().setUp()
        self._temp_directory = tempfile.TemporaryDirectory()
        self.MEDIA_ROOT = self._temp_directory.name

    def tearDown(self):
        self._temp_directory.cleanup()
        super().tearDown()

    def _authorize(self, username):
        """Authorize client and return the user."""
        user, _ = User.objects.get_or_create(username=username)
        self.client.force_authenticate(user=user)
        return user


class TestJobLogsCoverage(BaseJobLogsTest):
    """Coverage tests for job logs endpoints

    Verify that logs are correctly retrieved from each source

    Source              | /logs                                | /provider-logs
    --------------------|--------------------------------------|---------------------------------
    COS (user job)      | test_job_logs_in_storage_user_job    | (*)
    COS (provider job)  | (**)                                 | test_job_provider_logs_in_storage
    Ray (user job)      | test_job_logs_in_ray                 | (*)
    Ray (provider job)  | (**)                                 | test_job_provider_logs_in_ray
    DB legacy (user)    | test_job_logs_in_db                  | (*)
    DB legacy (provider)| (**)                                 | test_job_provider_logs_in_db
    No logs (provider)  | (**)                                 | test_job_provider_logs_not_found_empty
    Ray error           | test_job_logs_error                  | test_job_provider_logs_error

    (*) /provider-logs always returns 403 for user jobs (no provider)
    (**) /logs always returns 403 for providers.
    """

    @patch("scheduler.management.commands.update_jobs_statuses.get_job_handler")
    def test_job_logs_in_storage_user_job(self, get_job_handler_mock):
        """Tests /logs with user job from COS.

        For user jobs, all logs are shown with prefixes removed.
        """
        job = create_job(author="author")  # User job (no provider)

        # Mock Ray to return logs with all types
        full_logs = """
[PUBLIC] Public message
[PRIVATE] Private message

Unprefixed message
"""
        ray_client = Mock()
        ray_client.get_job_status.return_value = JobStatus.SUCCEEDED
        ray_client.get_job_logs.return_value = full_logs
        get_job_handler_mock.return_value = JobHandler(ray_client)

        # Execute update_jobs_statuses to detect terminal state and save logs
        call_command("update_jobs_statuses")

        # Call endpoint and verify logs are retrieved from storage
        self._authorize("author")
        jobs_response = self.client.get(
            reverse("v1:jobs-logs", args=[str(job.id)]),
            format="json",
        )

        self.assertEqual(jobs_response.status_code, HTTP_200_OK)
        # User jobs: all logs shown, prefixes removed
        expected_logs = """
Public message
Private message

Unprefixed message
"""
        self.assertEqual(jobs_response.data.get("logs"), expected_logs)

    @patch("api.use_cases.jobs.get_logs.get_job_handler")
    @patch("api.services.storage.logs_storage.LogsStorage.get_public_logs")
    def test_job_logs_in_ray(self, logs_storage_get_mock, get_job_handler_mock):
        """Tests /logs with user job from Ray."""
        logs_storage_get_mock.return_value = None

        job_handler_mock = Mock()
        job_handler_mock.logs.return_value = """
[PUBLIC] INFO: Public log for user

[PRIVATE] INFO: Private log for provider only
[PUBLIC] INFO: Another public log
Internal system log
[PRIVATE] WARNING: Private warning
[PUBLIC] INFO: Final public log
"""
        expected_user_logs = """
INFO: Public log for user

INFO: Private log for provider only
INFO: Another public log
Internal system log
WARNING: Private warning
INFO: Final public log
"""
        get_job_handler_mock.return_value = job_handler_mock

        job = create_job(author="author")

        self._authorize("author")

        jobs_response = self.client.get(
            reverse("v1:jobs-logs", args=[str(job.id)]),
            format="json",
        )

        self.assertEqual(jobs_response.status_code, HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("logs"), expected_user_logs)

    @patch("api.services.storage.logs_storage.LogsStorage.get_public_logs")
    def test_job_logs_in_db(self, logs_storage_get_mock):
        """Tests /logs with user job from DB (legacy)."""
        logs_storage_get_mock.return_value = None

        job = create_job(author="author")
        job.logs = "log from db"
        # this is needed so that it looks like the job has finished
        job.compute_resource = None
        job.save()

        self._authorize("author")
        jobs_response = self.client.get(
            reverse("v1:jobs-logs", args=[str(job.id)]),
            format="json",
        )

        self.assertEqual(jobs_response.status_code, HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("logs"), "log from db")

    @patch("api.use_cases.jobs.get_logs.get_job_handler")
    @patch("api.services.storage.logs_storage.LogsStorage.get_public_logs")
    def test_job_logs_error(self, logs_storage_get_mock, get_job_handler_mock):
        """Tests /logs with user job, Ray error."""
        logs_storage_get_mock.return_value = None
        get_job_handler_mock.side_effect = ConnectionError("Cannot connect to Ray")

        job = create_job(author="author")

        self._authorize("author")
        jobs_response = self.client.get(
            reverse("v1:jobs-logs", args=[str(job.id)]),
            format="json",
        )

        self.assertEqual(jobs_response.status_code, HTTP_200_OK)
        self.assertEqual(
            jobs_response.data.get("logs"),
            "Logs not available for this job during execution.",
        )

    @patch("scheduler.management.commands.update_jobs_statuses.get_job_handler")
    def test_job_provider_logs_in_storage(self, get_job_handler_mock):
        """Tests /provider-logs with provider job from COS.

        For provider jobs, /provider-logs shows all logs unfiltered (with prefixes).
        """
        # All log types with prefixes maintained
        full_logs = """[PUBLIC] Public message
[PRIVATE] Private message
Unprefixed message

[PUBLIC] Another public message
"""
        expected_provider_logs = """Private message
Unprefixed message

"""

        job = create_job(author="author", provider_admin="provider_admin")

        # Mock Ray to return logs (all logs saved for provider private logs)
        ray_client = Mock()
        ray_client.get_job_status.return_value = JobStatus.SUCCEEDED
        ray_client.get_job_logs.return_value = full_logs
        get_job_handler_mock.return_value = JobHandler(ray_client)

        # Execute update_jobs_statuses to detect terminal state and save logs
        call_command("update_jobs_statuses")

        # Call endpoint and verify logs are retrieved from storage
        self._authorize("provider_admin")
        jobs_response = self.client.get(
            reverse("v1:jobs-provider-logs", args=[str(job.id)]),
            format="json",
        )

        self.assertEqual(jobs_response.status_code, HTTP_200_OK)
        # /provider-logs returns all logs unfiltered (with prefixes)
        self.assertEqual(jobs_response.data.get("logs"), expected_provider_logs)

    @patch("api.use_cases.jobs.provider_logs.get_job_handler")
    @patch("api.services.storage.logs_storage.LogsStorage.get_private_logs")
    def test_job_provider_logs_in_ray(
        self, logs_storage_get_mock, get_job_handler_mock
    ):
        """Tests /provider-logs with provider job from Ray."""
        logs_storage_get_mock.return_value = None

        full_logs = """
[PUBLIC] INFO: Public log for user

[PRIVATE] INFO: Private log for provider only
[PUBLIC] INFO: Another public log
Internal system log
[PRIVATE] WARNING: Private warning
[PUBLIC] INFO: Final public log
"""
        expected_provider_logs = """

INFO: Private log for provider only
Internal system log
WARNING: Private warning
"""

        job_handler_mock = Mock()
        job_handler_mock.logs.return_value = full_logs
        get_job_handler_mock.return_value = job_handler_mock

        job = create_job(author="author", provider_admin="provider_admin")

        self._authorize("provider_admin")

        jobs_response = self.client.get(
            reverse("v1:jobs-provider-logs", args=[str(job.id)]),
            format="json",
        )

        self.assertEqual(jobs_response.status_code, HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("logs"), expected_provider_logs)

    @patch("api.services.storage.logs_storage.LogsStorage.get_private_logs")
    def test_job_provider_logs_in_db(self, logs_storage_get_mock):
        """Tests /provider-logs with provider job from DB (legacy)."""
        logs_storage_get_mock.return_value = None
        job = create_job(author="author", provider_admin="provider_admin")
        job.logs = "log entry 1"
        # this is needed so that it looks like the job has finished
        job.compute_resource = None
        job.save()

        self._authorize("provider_admin")
        jobs_response = self.client.get(
            reverse("v1:jobs-provider-logs", args=[str(job.id)]),
            format="json",
        )

        self.assertEqual(jobs_response.status_code, HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("logs"), "log entry 1")

    def test_job_provider_logs_not_found_empty(self):
        """Tests /provider-logs with provider job, no logs available."""
        job = create_job(author="author", provider_admin="provider_admin")
        # this is needed so that it looks like the job has finished
        job.compute_resource = None
        job.save()

        self._authorize("provider_admin")
        jobs_response = self.client.get(
            reverse("v1:jobs-provider-logs", args=[str(job.id)]),
            format="json",
        )

        self.assertEqual(jobs_response.status_code, HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("logs"), "No logs yet.")

    @patch("api.use_cases.jobs.provider_logs.get_job_handler")
    @patch("api.services.storage.logs_storage.LogsStorage.get_private_logs")
    def test_job_provider_logs_error(self, logs_storage_get_mock, get_job_handler_mock):
        """Tests /provider-logs with provider job, Ray error."""
        logs_storage_get_mock.return_value = None
        get_job_handler_mock.side_effect = ConnectionError("Cannot connect to Ray")

        job = create_job(author="author", provider_admin="provider_admin")

        self._authorize("provider_admin")
        jobs_response = self.client.get(
            reverse("v1:jobs-provider-logs", args=[str(job.id)]),
            format="json",
        )

        self.assertEqual(jobs_response.status_code, HTTP_200_OK)
        self.assertEqual(
            jobs_response.data.get("logs"),
            "Logs not available for this job during execution.",
        )
