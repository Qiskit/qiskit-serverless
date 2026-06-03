"""Tests for job logs APIs."""

from collections import deque
from typing import Optional
from unittest.mock import Mock, MagicMock, patch

import pytest
from django.contrib.auth.models import User, Group
from django.urls import reverse
from rest_framework.status import HTTP_200_OK, HTTP_403_FORBIDDEN
from rest_framework.test import APIClient

from prometheus_client import CollectorRegistry

from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import ComputeResource, Job, Program, Provider
from core.services.runners import RunnerError
from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.tasks.update_ray_jobs_statuses import UpdateRayJobsStatuses
from tests.utils import TestUtils


def create_job(author: str, provider_admin: Optional[str] = None) -> Job:
    """Create a job for testing."""
    author_user, _ = User.objects.get_or_create(username=author)
    provider = None

    if provider_admin:
        TestUtils.add_user_to_group(provider_admin, provider_admin)
        provider = TestUtils.get_or_create_provider(provider_admin, provider_admin)

    program = TestUtils.create_program(
        program_title=f"{author_user.username}-{provider_admin or 'custom'}",
        author=author_user,
        provider=provider,
    )

    compute_resource = ComputeResource.objects.create(title="test-cluster-storage-provider-logs", active=True)

    return TestUtils.create_job(
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
    @patch("api.use_cases.jobs.get_logs.get_runner")
    @patch("api.use_cases.jobs.provider_logs.get_runner")
    def test_endpoint_permissions(
        self, mock_provider_logs_handler, mock_get_logs_handler, endpoint, caller, provider_admin, expected_status
    ):
        """Test permissions for /logs and /provider-logs endpoints."""
        # Mock the runner clients to prevent hanging on Ray connection
        mock_handler = Mock()
        mock_handler.logs.return_value = "Test logs"
        mock_handler.provider_logs.return_value = "Test logs"
        mock_get_logs_handler.return_value = mock_handler
        mock_provider_logs_handler.return_value = mock_handler

        user_caller, _ = User.objects.get_or_create(username=caller)
        job = create_job(author="author", provider_admin=provider_admin)

        token = MagicMock()
        token.accessible_functions = FunctionAccessResult(use_legacy_authorization=True)
        client = APIClient()
        client.force_authenticate(user=user_caller, token=token)
        response = client.get(reverse(endpoint, args=[str(job.id)]), format="json")

        assert response.status_code == expected_status


@pytest.mark.django_db
class TestJobLogsCoverage:
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

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)
        self.client = APIClient()
        self.metrics = SchedulerMetrics(CollectorRegistry())

    def _authorize(self, username):
        """Authorize client and return the user."""
        user, _ = User.objects.get_or_create(username=username)
        token = MagicMock()
        token.accessible_functions = FunctionAccessResult(use_legacy_authorization=True)
        self.client.force_authenticate(user=user, token=token)
        return user

    @patch("scheduler.tasks.update_ray_jobs_statuses.get_runner")
    def test_job_logs_in_storage_user_job(self, get_runner_client_mock):
        """Tests /logs with user job from COS.

        For user jobs, all logs are shown with prefixes removed.
        """
        job = create_job(author="author")  # User job (no provider)

        # Mock RunnerClient to return logs with all types
        full_logs = """
[PUBLIC] Public message
[PRIVATE] Private message

Unprefixed message
"""
        runner_mock = Mock()
        runner_mock.status.return_value = Job.SUCCEEDED
        runner_mock.logs.return_value = deque(full_logs.splitlines())
        get_runner_client_mock.return_value = runner_mock

        # Execute update_jobs_statuses to detect terminal state and save logs
        UpdateRayJobsStatuses(kill_signal=KillSignal(), metrics=self.metrics).run()

        # Call endpoint and verify logs are retrieved from storage
        self._authorize("author")
        jobs_response = self.client.get(
            reverse("v1:jobs-logs", args=[str(job.id)]),
            format="json",
        )

        assert jobs_response.status_code == HTTP_200_OK
        # User jobs: all logs shown, prefixes removed
        expected_logs = """
Public message
Private message

Unprefixed message
"""
        assert jobs_response.data.get("logs") == expected_logs

    @patch("api.use_cases.jobs.get_logs.get_runner")
    @patch("core.services.storage.logs_storage_ray.RayLogsStorage.get_public_logs")
    def test_job_logs_in_ray(self, logs_storage_get_mock, get_runner_client_mock):
        """Tests /logs with user job from Ray."""
        logs_storage_get_mock.return_value = None

        runner_mock = Mock()
        runner_mock.logs.return_value = deque(
            [
                "",
                "[PUBLIC] INFO: Public log for user",
                "",
                "[PRIVATE] INFO: Private log for provider only",
                "[PUBLIC] INFO: Another public log",
                "Internal system log",
                "[PRIVATE] WARNING: Private warning",
                "[PUBLIC] INFO: Final public log",
            ]
        )
        expected_user_logs = """
INFO: Public log for user

INFO: Private log for provider only
INFO: Another public log
Internal system log
WARNING: Private warning
INFO: Final public log
"""
        get_runner_client_mock.return_value = runner_mock

        job = create_job(author="author")

        self._authorize("author")

        jobs_response = self.client.get(
            reverse("v1:jobs-logs", args=[str(job.id)]),
            format="json",
        )

        assert jobs_response.status_code == HTTP_200_OK
        assert jobs_response.data.get("logs") == expected_user_logs

    @patch("core.services.storage.logs_storage_ray.RayLogsStorage.get_public_logs")
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

        assert jobs_response.status_code == HTTP_200_OK
        assert jobs_response.data.get("logs") == "log from db"

    @patch("api.use_cases.jobs.get_logs.get_runner")
    @patch("core.services.storage.logs_storage_ray.RayLogsStorage.get_public_logs")
    def test_job_logs_error(self, logs_storage_get_mock, get_runner_client_mock):
        """Tests /logs with user job, Ray error."""
        logs_storage_get_mock.return_value = None
        runner_mock = Mock()
        runner_mock.logs.side_effect = RunnerError("Cannot connect to Ray")
        get_runner_client_mock.return_value = runner_mock

        job = create_job(author="author")

        self._authorize("author")
        jobs_response = self.client.get(
            reverse("v1:jobs-logs", args=[str(job.id)]),
            format="json",
        )

        assert jobs_response.status_code == HTTP_200_OK
        assert jobs_response.data.get("logs") == "Logs not available for this job during execution."

    @patch("scheduler.tasks.update_ray_jobs_statuses.get_runner")
    def test_job_provider_logs_in_storage(self, get_runner_client_mock):
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

        # Mock RunnerClient to return logs (all logs saved for provider private logs)
        runner_mock = Mock()
        runner_mock.status.return_value = Job.SUCCEEDED
        runner_mock.logs.return_value = deque(full_logs.splitlines())
        get_runner_client_mock.return_value = runner_mock

        # Execute update_jobs_statuses to detect terminal state and save logs
        UpdateRayJobsStatuses(kill_signal=KillSignal(), metrics=self.metrics).run()

        # Call endpoint and verify logs are retrieved from storage
        self._authorize("provider_admin")
        jobs_response = self.client.get(
            reverse("v1:jobs-provider-logs", args=[str(job.id)]),
            format="json",
        )

        assert jobs_response.status_code == HTTP_200_OK
        # /provider-logs returns all logs unfiltered (with prefixes)
        assert jobs_response.data.get("logs") == expected_provider_logs

    @patch("api.use_cases.jobs.provider_logs.get_runner")
    @patch("core.services.storage.logs_storage_ray.RayLogsStorage.get_private_logs")
    def test_job_provider_logs_in_ray(self, logs_storage_get_mock, get_runner_client_mock):
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

        runner_mock = Mock()
        runner_mock.provider_logs.return_value = deque(full_logs.splitlines())
        get_runner_client_mock.return_value = runner_mock

        job = create_job(author="author", provider_admin="provider_admin")

        self._authorize("provider_admin")

        jobs_response = self.client.get(
            reverse("v1:jobs-provider-logs", args=[str(job.id)]),
            format="json",
        )

        assert jobs_response.status_code == HTTP_200_OK
        assert jobs_response.data.get("logs") == expected_provider_logs

    @patch("core.services.storage.logs_storage_ray.RayLogsStorage.get_private_logs")
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

        assert jobs_response.status_code == HTTP_200_OK
        assert jobs_response.data.get("logs") == "log entry 1"

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

        assert jobs_response.status_code == HTTP_200_OK
        assert jobs_response.data.get("logs") == "No logs yet."

    @patch("api.use_cases.jobs.provider_logs.get_runner")
    @patch("core.services.storage.logs_storage_ray.RayLogsStorage.get_private_logs")
    def test_job_provider_logs_error(self, logs_storage_get_mock, get_runner_client_mock):
        """Tests /provider-logs with provider job, Ray error."""
        logs_storage_get_mock.return_value = None
        runner_mock = Mock()
        runner_mock.provider_logs.side_effect = RunnerError("Cannot connect to Ray")
        get_runner_client_mock.return_value = runner_mock

        job = create_job(author="author", provider_admin="provider_admin")

        self._authorize("provider_admin")
        jobs_response = self.client.get(
            reverse("v1:jobs-provider-logs", args=[str(job.id)]),
            format="json",
        )

        assert jobs_response.status_code == HTTP_200_OK
        assert jobs_response.data.get("logs") == f"Logs not available for job [{job.id}] during execution."


@pytest.mark.django_db
class TestFleetJobLogsEndpoint:
    """Test /logs and /provider-logs view responses for Fleet jobs."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.client = APIClient()

    def _authorize(self, username):
        user, _ = User.objects.get_or_create(username=username)
        token = MagicMock()
        token.accessible_functions = FunctionAccessResult(use_legacy_authorization=True)
        self.client.force_authenticate(user=user, token=token)
        return user

    def _make_fleet_job(self, author_username):
        ce_project = TestUtils.get_or_create_ce_project(
            project_name="test-project",
            project_id="test-ce-project-id",
            cos_bucket_user_data_name="user-bucket",
            cos_bucket_provider_data_name="provider-bucket",
            cos_instance_name="cos-instance",
            cos_key_name="cos-key",
        )
        program = TestUtils.create_program(
            program_title="fleet-func",
            author=author_username,
            runner=Program.FLEETS,
        )
        author, _ = User.objects.get_or_create(username=author_username)
        return TestUtils.create_job(author=author, program=program, code_engine_project=ce_project)

    @patch("api.use_cases.jobs.get_logs.get_logs_storage")
    def test_fleet_logs_returns_302_when_logs_exist(self, mock_storage):
        """Fleet /logs: 302 redirect when COS object exists."""
        presigned_url = "https://cos.example.com/logs.log?sig=abc"
        mock_storage.return_value.get_public_logs_url.return_value = presigned_url

        job = self._make_fleet_job("author")
        self._authorize("author")

        response = self.client.get(
            reverse("v1:jobs-logs", args=[str(job.id)]),
            format="json",
        )

        assert response.status_code == 302
        assert response["Location"] == presigned_url

    @patch("api.use_cases.jobs.get_logs.get_logs_storage")
    def test_fleet_logs_returns_204_when_no_logs(self, mock_storage):
        """Fleet /logs: 204 No Content when COS object does not exist yet."""
        mock_storage.return_value.get_public_logs_url.return_value = None

        job = self._make_fleet_job("author")
        self._authorize("author")

        response = self.client.get(
            reverse("v1:jobs-logs", args=[str(job.id)]),
            format="json",
        )

        assert response.status_code == 204

    @patch("api.use_cases.jobs.provider_logs.get_logs_storage")
    def test_fleet_provider_logs_returns_302_when_logs_exist(self, mock_storage):
        """Fleet /provider-logs: 302 redirect when COS private log object exists."""
        presigned_url = "https://cos.example.com/private.log?sig=xyz"
        mock_storage.return_value.get_private_logs_url.return_value = presigned_url

        ce_project = TestUtils.get_or_create_ce_project(
            project_name="provider-project",
            project_id="provider-ce-project-id",
            cos_bucket_user_data_name="user-bucket",
            cos_bucket_provider_data_name="provider-bucket",
            cos_instance_name="cos-instance",
            cos_key_name="cos-key",
        )
        provider = TestUtils.get_or_create_provider("fleet-provider", "fleet-provider-group")
        program = TestUtils.create_program(
            program_title="provider-fleet-func",
            author="provider-author",
            provider=provider,
            runner=Program.FLEETS,
        )
        author, _ = User.objects.get_or_create(username="provider-author")
        job = TestUtils.create_job(author=author, program=program, code_engine_project=ce_project)

        admin, _ = User.objects.get_or_create(username="provider-admin-user")
        TestUtils.add_user_to_group("provider-admin-user", "fleet-provider-group")

        token = MagicMock()
        token.accessible_functions = FunctionAccessResult(use_legacy_authorization=True)
        self.client.force_authenticate(user=admin, token=token)

        response = self.client.get(
            reverse("v1:jobs-provider-logs", args=[str(job.id)]),
            format="json",
        )

        assert response.status_code == 302
        assert response["Location"] == presigned_url

    @patch("api.use_cases.jobs.provider_logs.get_logs_storage")
    def test_fleet_provider_logs_returns_204_when_no_logs(self, mock_storage):
        """Fleet /provider-logs: 204 No Content when COS private log does not exist yet."""
        mock_storage.return_value.get_private_logs_url.return_value = None

        ce_project = TestUtils.get_or_create_ce_project(
            project_name="provider-project-2",
            project_id="provider-ce-project-id-2",
            cos_bucket_user_data_name="user-bucket",
            cos_bucket_provider_data_name="provider-bucket",
            cos_instance_name="cos-instance",
            cos_key_name="cos-key",
        )
        provider = TestUtils.get_or_create_provider("fleet-provider-2", "fleet-provider-group-2")
        program = TestUtils.create_program(
            program_title="provider-fleet-func-2",
            author="provider-author-2",
            provider=provider,
            runner=Program.FLEETS,
        )
        author, _ = User.objects.get_or_create(username="provider-author-2")
        job = TestUtils.create_job(author=author, program=program, code_engine_project=ce_project)

        admin, _ = User.objects.get_or_create(username="provider-admin-user-2")
        TestUtils.add_user_to_group("provider-admin-user-2", "fleet-provider-group-2")

        token = MagicMock()
        token.accessible_functions = FunctionAccessResult(use_legacy_authorization=True)
        self.client.force_authenticate(user=admin, token=token)

        response = self.client.get(
            reverse("v1:jobs-provider-logs", args=[str(job.id)]),
            format="json",
        )

        assert response.status_code == 204
