"""Tests for job logs APIs."""

from typing import Optional
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth.models import User, Group
from django.urls import reverse
from rest_framework.status import HTTP_200_OK, HTTP_403_FORBIDDEN
from rest_framework.test import APIClient

from prometheus_client import CollectorRegistry

from core.models import ComputeResource, Job, Program, Provider
from core.services.runners.runner import RunnerError
from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.tasks.update_jobs_statuses import UpdateJobsStatuses


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

    compute_resource = ComputeResource.objects.create(title="test-cluster-storage-provider-logs", active=True)

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
    @patch("core.services.runners.runner.Runner.get")
    def test_endpoint_permissions(self, mock_runner_get, endpoint, caller, provider_admin, expected_status):
        """Test permissions for /logs and /provider-logs endpoints."""
        # Mock the runner clients to prevent hanging on Ray connection
        mock_handler = Mock()
        mock_handler.logs.return_value = "Test logs"
        mock_handler.provider_logs.return_value = "Test logs"
        mock_runner_get.return_value = mock_handler

        user_caller, _ = User.objects.get_or_create(username=caller)
        job = create_job(author="author", provider_admin=provider_admin)

        client = APIClient()
        client.force_authenticate(user=user_caller)
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
        self.client.force_authenticate(user=user)
        return user

    @patch("core.services.runners.runner.Runner.get")
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
        runner_mock.logs.return_value = full_logs
        get_runner_client_mock.return_value = runner_mock

        # Execute update_jobs_statuses to detect terminal state and save logs
        UpdateJobsStatuses(kill_signal=KillSignal(), metrics=self.metrics).run()

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

    @patch("core.services.runners.runner.Runner.get")
    @patch("core.services.storage.logs_storage.LogsStorage.get_public_logs")
    def test_job_logs_in_ray(self, logs_storage_get_mock, get_runner_client_mock):
        """Tests /logs with user job from Ray."""
        logs_storage_get_mock.return_value = None

        runner_mock = Mock()
        runner_mock.logs.return_value = """
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
        get_runner_client_mock.return_value = runner_mock

        job = create_job(author="author")

        self._authorize("author")

        jobs_response = self.client.get(
            reverse("v1:jobs-logs", args=[str(job.id)]),
            format="json",
        )

        assert jobs_response.status_code == HTTP_200_OK
        assert jobs_response.data.get("logs") == expected_user_logs

    @patch("core.services.storage.logs_storage.LogsStorage.get_public_logs")
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

    @patch("core.services.runners.runner.Runner.get")
    @patch("core.services.storage.logs_storage.LogsStorage.get_public_logs")
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

    @patch("core.services.runners.runner.Runner.get")
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
        runner_mock.logs.return_value = full_logs
        get_runner_client_mock.return_value = runner_mock

        # Execute update_jobs_statuses to detect terminal state and save logs
        UpdateJobsStatuses(kill_signal=KillSignal(), metrics=self.metrics).run()

        # Call endpoint and verify logs are retrieved from storage
        self._authorize("provider_admin")
        jobs_response = self.client.get(
            reverse("v1:jobs-provider-logs", args=[str(job.id)]),
            format="json",
        )

        assert jobs_response.status_code == HTTP_200_OK
        # /provider-logs returns all logs unfiltered (with prefixes)
        assert jobs_response.data.get("logs") == expected_provider_logs

    @patch("core.services.runners.runner.Runner.get")
    @patch("core.services.storage.logs_storage.LogsStorage.get_private_logs")
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
        runner_mock.provider_logs.return_value = full_logs
        get_runner_client_mock.return_value = runner_mock

        job = create_job(author="author", provider_admin="provider_admin")

        self._authorize("provider_admin")

        jobs_response = self.client.get(
            reverse("v1:jobs-provider-logs", args=[str(job.id)]),
            format="json",
        )

        assert jobs_response.status_code == HTTP_200_OK
        assert jobs_response.data.get("logs") == expected_provider_logs

    @patch("core.services.storage.logs_storage.LogsStorage.get_private_logs")
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

    @patch("core.services.runners.runner.Runner.get")
    @patch("core.services.storage.logs_storage.LogsStorage.get_private_logs")
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
