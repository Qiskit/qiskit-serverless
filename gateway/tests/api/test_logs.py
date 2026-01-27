"""Tests for job logs APIs."""

import tempfile
from typing import Optional
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth.models import User, Group
from django.urls import reverse
from rest_framework.status import HTTP_200_OK, HTTP_403_FORBIDDEN
from rest_framework.test import APITestCase, APIClient

from api.models import ComputeResource, Job, Program, Provider
from api.use_cases.jobs.get_logs import GetJobLogsUseCase
from api.use_cases.jobs.provider_logs import GetProviderJobLogsUseCase


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

    return Job.objects.create(author=author_user, program=program)


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
            ("v1:jobs-logs", "provider", "provider", HTTP_200_OK),
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
    COS (provider job)  | test_job_logs_in_storage_provider_job| test_job_provider_logs_in_storage
    Ray (user job)      | test_job_logs_in_ray                 | (*)
    Ray (provider job)  | test_job_logs_in_ray_with_provider   | test_job_provider_logs_in_ray
    DB legacy (user)    | test_job_logs_in_db                  | (*)
    DB legacy (provider)| test_job_logs_not_found_empty        | test_job_provider_logs_in_db
    No logs (provider)  | (same as DB legacy)                  | test_job_provider_logs_not_found_empty
    Ray error           | test_job_logs_error                  | test_job_provider_logs_error

    (*) /provider-logs always returns 403 for user jobs (no provider)
    """

    @patch("api.services.storage.logs_storage.LogsStorage.get_public_logs")
    def test_job_logs_in_storage_user_job(self, logs_storage_get_mock):
        """Tests /logs with user job from COS."""
        logs_storage_get_mock.return_value = "from storage"
        job = create_job(author="author")  # User job (no provider)

        self._authorize("author")
        jobs_response = self.client.get(
            reverse("v1:jobs-logs", args=[str(job.id)]),
            format="json",
        )

        self.assertEqual(jobs_response.status_code, HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("logs"), "from storage")

    @patch("api.services.storage.logs_storage.LogsStorage.get_public_logs")
    def test_job_logs_in_storage_provider_job(self, logs_storage_get_mock):
        """Tests /logs with provider job from COS."""
        logs_storage_get_mock.return_value = "from storage"
        job = create_job(author="author", provider_admin="provider_admin")

        self._authorize("provider_admin")
        jobs_response = self.client.get(
            reverse("v1:jobs-logs", args=[str(job.id)]),
            format="json",
        )

        self.assertEqual(jobs_response.status_code, HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("logs"), "from storage")

    @patch("api.use_cases.jobs.get_logs.get_job_handler")
    @patch("api.services.storage.logs_storage.LogsStorage.get_public_logs")
    def test_job_logs_in_ray(self, logs_storage_get_mock, get_job_handler_mock):
        """Tests /logs with user job from Ray."""
        logs_storage_get_mock.return_value = None

        job_handler_mock = Mock()
        job_handler_mock.logs.return_value = """
[PUBLIC] INFO:user: Public log for user

[PRIVATE] INFO:provider: Private log for provider only
[PUBLIC] INFO:user: Another public log
Internal system log
[PRIVATE] WARNING:provider: Private warning
[PUBLIC] INFO:user: Final public log
"""
        expected_user_logs = """
INFO:user: Public log for user

INFO:provider: Private log for provider only
INFO:user: Another public log
Internal system log
WARNING:provider: Private warning
INFO:user: Final public log
"""
        get_job_handler_mock.return_value = job_handler_mock

        # Add an active compute_resource to the job, so the endpoint could try to reach Ray
        job = create_job(author="author")
        job.compute_resource = ComputeResource.objects.create(
            title="test-cluster-2", active=True
        )
        job.save()

        self._authorize("author")

        with self.settings(RAY_SETUP_MAX_RETRIES=2):
            jobs_response = self.client.get(
                reverse("v1:jobs-logs", args=[str(job.id)]),
                format="json",
            )

        self.assertEqual(jobs_response.status_code, HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("logs"), expected_user_logs)

    @patch("api.use_cases.jobs.get_logs.get_job_handler")
    @patch("api.services.storage.logs_storage.LogsStorage.get_public_logs")
    def test_job_logs_in_ray_with_provider(
        self, logs_storage_get_mock, get_job_handler_mock
    ):
        """Tests /logs with provider job from Ray."""
        logs_storage_get_mock.return_value = None

        full_logs = """
[PUBLIC] INFO:user: Public log for user

[PRIVATE] INFO:provider: Private log for provider only
[PUBLIC] INFO:user: Another public log
Internal system log
[PRIVATE] WARNING:provider: Private warning
[PUBLIC] INFO:user: Final public log
"""
        expected_user_logs = """INFO:user: Public log for user
INFO:user: Another public log
INFO:user: Final public log
"""

        job_handler_mock = Mock()
        job_handler_mock.logs.return_value = full_logs
        get_job_handler_mock.return_value = job_handler_mock

        # Add an active compute_resource to the job, so the endpoint could try to reach Ray
        job = create_job(author="author", provider_admin="provider_admin")
        job.compute_resource = ComputeResource.objects.create(
            title="test-cluster-3", active=True
        )
        job.save()

        self._authorize("provider_admin")

        with self.settings(RAY_SETUP_MAX_RETRIES=2):
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
        job.save()

        self._authorize("author")
        jobs_response = self.client.get(
            reverse("v1:jobs-logs", args=[str(job.id)]),
            format="json",
        )

        self.assertEqual(jobs_response.status_code, HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("logs"), "log from db")

    @patch("api.services.storage.logs_storage.LogsStorage.get_public_logs")
    def test_job_logs_not_found_empty(self, logs_storage_get_mock):
        """Tests /logs with provider job, no logs available."""
        logs_storage_get_mock.return_value = None
        job = create_job(author="author", provider_admin="provider_admin")

        self._authorize("provider_admin")
        jobs_response = self.client.get(
            reverse("v1:jobs-logs", args=[str(job.id)]),
            format="json",
        )

        self.assertEqual(jobs_response.status_code, HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("logs"), "No logs available.")

    def test_job_logs_error(self):
        """Tests /logs with user job, Ray error."""
        user = self._authorize("test_user_2")

        # The job author must match the user for authorization to pass
        compute_resource = Mock(active=True, host="http://wrong-host")
        program = Mock(title="fake_fn", provider=None)
        author = Mock(id=user.id, username=user.username)
        job = Mock(
            id="fake-job-id",
            compute_resource=compute_resource,
            program=program,
            author=author,
        )

        use_case = GetJobLogsUseCase()
        use_case.jobs_repository = Mock()
        use_case.jobs_repository.get_job_by_id.return_value = job

        with self.settings(RAY_SETUP_MAX_RETRIES=2, MEDIA_ROOT=self.MEDIA_ROOT):
            message = use_case.execute("fake_job_id", user)

        self.assertEqual(message, "Logs not available for this job during execution.")

    # ==========================================================================
    # COVERAGE TESTS: /provider-logs endpoint - Data sources
    # ==========================================================================

    @patch("api.services.storage.logs_storage.LogsStorage.get_private_logs")
    def test_job_provider_logs_in_storage(self, logs_storage_get_mock):
        """Tests /provider-logs with provider job from COS."""
        logs_storage_get_mock.return_value = "from storage"
        job = create_job(author="author", provider_admin="provider_admin")

        self._authorize("provider_admin")
        jobs_response = self.client.get(
            reverse("v1:jobs-provider-logs", args=[str(job.id)]),
            format="json",
        )

        self.assertEqual(jobs_response.status_code, HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("logs"), "from storage")

    @patch("api.use_cases.jobs.provider_logs.get_job_handler")
    @patch("api.services.storage.logs_storage.LogsStorage.get_private_logs")
    def test_job_provider_logs_in_ray(
        self, logs_storage_get_mock, get_job_handler_mock
    ):
        """Tests /provider-logs with provider job from Ray."""
        logs_storage_get_mock.return_value = None

        full_logs = """
[PUBLIC] INFO:user: Public log for user

[PRIVATE] INFO:provider: Private log for provider only
[PUBLIC] INFO:user: Another public log
Internal system log
[PRIVATE] WARNING:provider: Private warning
[PUBLIC] INFO:user: Final public log
"""

        job_handler_mock = Mock()
        job_handler_mock.logs.return_value = full_logs
        get_job_handler_mock.return_value = job_handler_mock

        # Add an active compute_resource to the job, so the endpoint could try to reach Ray
        job = create_job(author="author", provider_admin="provider_admin")
        job.compute_resource = ComputeResource.objects.create(
            title="test-cluster", active=True
        )
        job.save()

        self._authorize("provider_admin")

        with self.settings(RAY_SETUP_MAX_RETRIES=2):
            jobs_response = self.client.get(
                reverse("v1:jobs-provider-logs", args=[str(job.id)]),
                format="json",
            )

        self.assertEqual(jobs_response.status_code, HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("logs"), full_logs)

    @patch("api.services.storage.logs_storage.LogsStorage.get_private_logs")
    def test_job_provider_logs_in_db(self, logs_storage_get_mock):
        """Tests /provider-logs with provider job from DB (legacy)."""
        logs_storage_get_mock.return_value = None
        job = create_job(author="author", provider_admin="provider_admin")
        job.logs = "log entry 1"
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

        self._authorize("provider_admin")
        jobs_response = self.client.get(
            reverse("v1:jobs-provider-logs", args=[str(job.id)]),
            format="json",
        )

        self.assertEqual(jobs_response.status_code, HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("logs"), "No logs yet.")

    def test_job_provider_logs_error(self):
        """Tests /provider-logs with provider job, Ray error."""
        user = self._authorize("test_user_2")

        compute_resource = Mock(active=True, host="http://wrong-host")
        provider = Mock(admin_groups=user.groups)
        provider.name = "fake_provider"
        program = Mock(provider=provider, title="fake_fn")
        author = Mock(username="fake_author")
        job = Mock(
            id="fake-job-id",
            compute_resource=compute_resource,
            program=program,
            author=author,
        )

        use_case = GetProviderJobLogsUseCase()
        use_case.jobs_repository = Mock()
        use_case.jobs_repository.get_job_by_id.return_value = job

        with self.settings(RAY_SETUP_MAX_RETRIES=2, MEDIA_ROOT=self.MEDIA_ROOT):
            message = use_case.execute("fake_job_id", user)

        self.assertEqual(message, "Logs not available for this job during execution.")
