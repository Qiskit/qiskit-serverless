# This code is a Qiskit project.
#
# (C) Copyright IBM 2025.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Tests for ServerlessClient job-related operations."""

import json
from unittest.mock import Mock, patch

import pytest
import requests_mock

from qiskit_serverless import ServerlessClient
from qiskit_serverless.core.job import Job, Configuration
from qiskit_serverless.core.function import QiskitFunction
from qiskit_serverless.exception import QiskitServerlessException


@pytest.fixture
def mock_client():
    """Create a mock ServerlessClient for testing."""
    with patch(
        "qiskit_serverless.core.clients.serverless_client.ServerlessClient._verify_credentials",
        Mock(),
    ):
        client = ServerlessClient(
            host="https://test-host.com",
            token="test-token",
            instance="test-instance",
            version="v1",
        )
        return client


@pytest.fixture
def mock_function():
    """Create a mock QiskitFunction for testing."""
    return QiskitFunction(
        title="test-function",
        provider="test-provider",
    )


class TestJobsMethod:
    """Test ServerlessClient.jobs() method."""

    def test_jobs_default_parameters(self, mock_client):
        """Test jobs() with default parameters."""
        mock_response = {
            "results": [
                {"id": "job-1", "status": "SUCCEEDED"},
                {"id": "job-2", "status": "RUNNING"},
            ]
        }

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/",
                json=mock_response,
            )

            jobs = mock_client.jobs()

            assert len(jobs) == 2
            assert jobs[0].job_id == "job-1"
            assert jobs[1].job_id == "job-2"
            assert isinstance(jobs[0], Job)

    @pytest.mark.parametrize(
        "limit,offset",
        [
            (5, 0),
            (10, 5),
            (20, 10),
            (100, 0),
        ],
    )
    def test_jobs_with_limit_and_offset(self, mock_client, limit, offset):
        """Test jobs() with various limit and offset parameters."""
        mock_response = {"results": [{"id": f"job-{i}", "status": "SUCCEEDED"} for i in range(limit)]}

        with requests_mock.Mocker() as mocker:
            mock_request = mocker.get(
                "https://test-host.com/api/v1/jobs/",
                json=mock_response,
            )

            jobs = mock_client.jobs(limit=limit, offset=offset)

            assert len(jobs) == limit
            # Verify query parameters were sent correctly
            assert mock_request.last_request.qs["limit"] == [str(limit)]
            assert mock_request.last_request.qs["offset"] == [str(offset)]

    @pytest.mark.parametrize(
        "status",
        [
            "QUEUED",
            "RUNNING",
            "DONE",
            "ERROR",
            "CANCELED",
        ],
    )
    def test_jobs_with_status_filter(self, mock_client, status):
        """Test jobs() with status filter."""
        mock_response = {"results": [{"id": "job-1", "status": status}]}

        with requests_mock.Mocker() as mocker:
            mock_request = mocker.get(
                "https://test-host.com/api/v1/jobs/",
                json=mock_response,
            )

            jobs = mock_client.jobs(status=status)

            assert len(jobs) == 1
            # Status should be mapped to serverless format
            assert "status" in mock_request.last_request.qs

    def test_jobs_with_created_after_filter(self, mock_client):
        """Test jobs() with created_after filter."""
        created_after = "2024-01-01T00:00:00Z"
        mock_response = {"results": [{"id": "job-1", "status": "SUCCEEDED"}]}

        with requests_mock.Mocker() as mocker:
            mock_request = mocker.get(
                "https://test-host.com/api/v1/jobs/",
                json=mock_response,
            )

            jobs = mock_client.jobs(created_after=created_after)

            assert len(jobs) == 1
            # URL encoding may lowercase the timestamp, so compare case-insensitively
            assert mock_request.last_request.qs["created_after"][0].lower() == created_after.lower()

    def test_jobs_with_function_filter(self, mock_client, mock_function):
        """Test jobs() with function filter."""
        mock_response = {"results": [{"id": "job-1", "status": "SUCCEEDED"}]}

        with requests_mock.Mocker() as mocker:
            mock_request = mocker.get(
                "https://test-host.com/api/v1/jobs/",
                json=mock_response,
            )

            jobs = mock_client.jobs(function=mock_function)

            assert len(jobs) == 1
            assert mock_request.last_request.qs["function"] == ["test-function"]
            assert mock_request.last_request.qs["provider"] == ["test-provider"]

    def test_jobs_empty_results(self, mock_client):
        """Test jobs() with empty results."""
        mock_response = {"results": []}

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/",
                json=mock_response,
            )

            jobs = mock_client.jobs()

            assert len(jobs) == 0
            assert jobs == []

    def test_jobs_with_raw_data(self, mock_client):
        """Test that jobs() preserves raw_data in Job objects."""
        mock_response = {
            "results": [
                {
                    "id": "job-1",
                    "status": "SUCCEEDED",
                    "created": "2024-01-01T00:00:00Z",
                    "result": "test-result",
                }
            ]
        }

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/",
                json=mock_response,
            )

            jobs = mock_client.jobs()

            assert jobs[0].raw_data["created"] == "2024-01-01T00:00:00Z"
            assert jobs[0].raw_data["result"] == "test-result"


class TestProviderJobsMethod:
    """Test ServerlessClient.provider_jobs() method."""

    def test_provider_jobs_success(self, mock_client, mock_function):
        """Test provider_jobs() with valid function."""
        mock_response = {
            "results": [
                {"id": "job-1", "status": "SUCCEEDED"},
                {"id": "job-2", "status": "RUNNING"},
            ]
        }

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/provider/",
                json=mock_response,
            )

            jobs = mock_client.provider_jobs(function=mock_function)

            assert len(jobs) == 2
            assert jobs[0].job_id == "job-1"
            assert jobs[1].job_id == "job-2"

    def test_provider_jobs_without_provider_raises_error(self, mock_client):
        """Test provider_jobs() raises error when function has no provider."""
        function_without_provider = QiskitFunction(title="test-function")

        with pytest.raises(QiskitServerlessException, match="doesn't have a provider"):
            mock_client.provider_jobs(function=function_without_provider)

    def test_provider_jobs_with_filters(self, mock_client, mock_function):
        """Test provider_jobs() with limit, offset, and status filters."""
        mock_response = {"results": [{"id": "job-1", "status": "SUCCEEDED"}]}

        with requests_mock.Mocker() as mocker:
            mock_request = mocker.get(
                "https://test-host.com/api/v1/jobs/provider/",
                json=mock_response,
            )

            jobs = mock_client.provider_jobs(
                function=mock_function,
                limit=5,
                offset=10,
                status="DONE",
            )

            assert len(jobs) == 1
            assert mock_request.last_request.qs["limit"] == ["5"]
            assert mock_request.last_request.qs["offset"] == ["10"]
            assert mock_request.last_request.qs["function"] == ["test-function"]
            assert mock_request.last_request.qs["provider"] == ["test-provider"]


class TestJobMethod:
    """Test ServerlessClient.job() method."""

    def test_job_retrieval_success(self, mock_client):
        """Test job() successfully retrieves a job."""
        mock_response = {
            "id": "test-job-id",
            "status": "SUCCEEDED",
            "result": "test-result",
        }

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job-id/",
                json=mock_response,
            )

            job = mock_client.job("test-job-id")

            assert job is not None
            assert job.job_id == "test-job-id"
            assert isinstance(job, Job)

    def test_job_not_found_returns_none(self, mock_client):
        """Test job() returns None when job doesn't exist."""
        mock_response = {}

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/nonexistent-job/",
                json=mock_response,
            )

            job = mock_client.job("nonexistent-job")

            assert job is None


class TestRunMethod:
    """Test ServerlessClient.run() method."""

    def test_run_with_function_object(self, mock_client, mock_function):
        """Test run() with QiskitFunction object."""
        mock_response = {"id": "new-job-id"}

        with requests_mock.Mocker() as mocker:
            mock_request = mocker.post(
                "https://test-host.com/api/v1/programs/run/",
                json=mock_response,
            )

            job = mock_client.run(program=mock_function)

            assert job.job_id == "new-job-id"
            assert isinstance(job, Job)

            # Verify request payload
            request_json = mock_request.last_request.json()
            assert request_json["title"] == "test-function"
            assert request_json["provider"] == "test-provider"

    def test_run_with_string_program(self, mock_client):
        """Test run() with string program name."""
        mock_response = {"id": "new-job-id"}

        with requests_mock.Mocker() as mocker:
            mock_request = mocker.post(
                "https://test-host.com/api/v1/programs/run/",
                json=mock_response,
            )

            job = mock_client.run(program="my-function", provider="my-provider")

            assert job.job_id == "new-job-id"

            # Verify request payload
            request_json = mock_request.last_request.json()
            assert request_json["title"] == "my-function"
            assert request_json["provider"] == "my-provider"

    def test_run_with_arguments(self, mock_client, mock_function):
        """Test run() with arguments."""
        arguments = {"param1": "value1", "param2": 42}
        mock_response = {"id": "new-job-id"}

        with requests_mock.Mocker() as mocker:
            mock_request = mocker.post(
                "https://test-host.com/api/v1/programs/run/",
                json=mock_response,
            )

            job = mock_client.run(program=mock_function, arguments=arguments)

            assert job.job_id == "new-job-id"

            # Verify arguments were serialized
            request_json = mock_request.last_request.json()
            assert "arguments" in request_json
            # Arguments should be JSON-encoded
            decoded_args = json.loads(request_json["arguments"])
            assert decoded_args == arguments

    def test_run_with_configuration(self, mock_client, mock_function):
        """Test run() with Configuration object."""
        config = Configuration(
            workers=4,
            min_workers=2,
            max_workers=8,
            auto_scaling=True,
        )
        mock_response = {"id": "new-job-id"}

        with requests_mock.Mocker() as mocker:
            mock_request = mocker.post(
                "https://test-host.com/api/v1/programs/run/",
                json=mock_response,
            )

            job = mock_client.run(program=mock_function, config=config)

            assert job.job_id == "new-job-id"

            # Verify config was included
            request_json = mock_request.last_request.json()
            assert "config" in request_json
            assert request_json["config"]["workers"] == 4
            assert request_json["config"]["auto_scaling"] is True

    def test_run_without_configuration_uses_default(self, mock_client, mock_function):
        """Test run() uses default Configuration when none provided."""
        mock_response = {"id": "new-job-id"}

        with requests_mock.Mocker() as mocker:
            mock_request = mocker.post(
                "https://test-host.com/api/v1/programs/run/",
                json=mock_response,
            )

            job = mock_client.run(program=mock_function)

            # Verify default config was included
            request_json = mock_request.last_request.json()
            assert "config" in request_json


class TestStatusMethod:
    """Test ServerlessClient.status() method."""

    @pytest.mark.parametrize(
        "status",
        [
            "QUEUED",
            "PENDING",
            "RUNNING",
            "SUCCEEDED",
            "FAILED",
            "STOPPED",
        ],
    )
    def test_status_returns_job_status(self, mock_client, status):
        """Test status() returns correct job status."""
        mock_response = {"id": "test-job", "status": status}

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/",
                json=mock_response,
            )

            result_status = mock_client.status("test-job")

            assert result_status == status

    def test_status_with_sub_status(self, mock_client):
        """Test status() returns sub_status when job is RUNNING."""
        mock_response = {
            "id": "test-job",
            "status": "RUNNING",
            "sub_status": "MAPPING",
        }

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/",
                json=mock_response,
            )

            result_status = mock_client.status("test-job")

            assert result_status == "MAPPING"

    def test_status_without_sub_status(self, mock_client):
        """Test status() returns main status when sub_status is None."""
        mock_response = {
            "id": "test-job",
            "status": "RUNNING",
            "sub_status": None,
        }

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/",
                json=mock_response,
            )

            result_status = mock_client.status("test-job")

            assert result_status == "RUNNING"

    def test_status_unknown_when_missing(self, mock_client):
        """Test status() returns 'Unknown' when status is missing."""
        mock_response = {"id": "test-job"}

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/",
                json=mock_response,
            )

            result_status = mock_client.status("test-job")

            assert result_status == "Unknown"

    def test_status_includes_with_result_false_param(self, mock_client):
        """Test status() includes with_result=false parameter."""
        mock_response = {"id": "test-job", "status": "SUCCEEDED"}

        with requests_mock.Mocker() as mocker:
            mock_request = mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/",
                json=mock_response,
            )

            mock_client.status("test-job")

            assert mock_request.last_request.qs["with_result"] == ["false"]


class TestStopMethod:
    """Test ServerlessClient.stop() method."""

    @patch("qiskit_serverless.core.clients.serverless_client.QiskitRuntimeService")
    def test_stop_without_service(self, mock_runtime_service_class, mock_client):
        """Test stop() creates QiskitRuntimeService when not provided."""
        mock_response = {"message": "Job stopped successfully"}
        # Create a mock with to_json method to avoid recursion during serialization
        mock_service_instance = Mock()
        mock_service_instance.to_json.return_value = '{"mock": "service"}'
        mock_runtime_service_class.return_value = mock_service_instance

        with requests_mock.Mocker() as mocker:
            mocker.post(
                "https://test-host.com/api/v1/jobs/test-job/stop/",
                json=mock_response,
            )

            result = mock_client.stop("test-job")

            assert result == "Job stopped successfully"
            mock_runtime_service_class.assert_called_once()

    def test_stop_with_service(self, mock_client):
        """Test stop() with provided QiskitRuntimeService."""
        mock_response = {"message": "Job stopped successfully"}
        # Create a mock with to_json method to avoid recursion during serialization
        mock_service = Mock()
        mock_service.to_json.return_value = '{"mock": "service"}'

        with requests_mock.Mocker() as mocker:
            mocker.post(
                "https://test-host.com/api/v1/jobs/test-job/stop/",
                json=mock_response,
            )

            result = mock_client.stop("test-job", service=mock_service)

            assert result == "Job stopped successfully"

    @patch("qiskit_serverless.core.clients.serverless_client.QiskitRuntimeService")
    def test_stop_handles_invalid_account_error(self, mock_runtime_service_class, mock_client):
        """Test stop() handles InvalidAccountError gracefully."""
        from qiskit_ibm_runtime.accounts.exceptions import InvalidAccountError

        mock_response = {"message": "Job stopped successfully"}
        mock_runtime_service_class.side_effect = InvalidAccountError("Invalid account")

        with requests_mock.Mocker() as mocker:
            mocker.post(
                "https://test-host.com/api/v1/jobs/test-job/stop/",
                json=mock_response,
            )

            with pytest.warns(UserWarning, match="No QiskitRuntimeService"):
                result = mock_client.stop("test-job")

            assert result == "Job stopped successfully"


class TestResultMethod:
    """Test ServerlessClient.result() method."""

    def test_result_returns_decoded_json(self, mock_client):
        """Test result() returns decoded JSON result."""
        mock_response = {
            "id": "test-job",
            "result": '{"key": "value", "number": 42}',
        }

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/",
                json=mock_response,
            )

            result = mock_client.result("test-job")

            assert result == {"key": "value", "number": 42}

    def test_result_with_empty_result(self, mock_client):
        """Test result() handles empty result."""
        mock_response = {"id": "test-job", "result": ""}

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/",
                json=mock_response,
            )

            result = mock_client.result("test-job")

            assert result == {}

    def test_result_with_null_result(self, mock_client):
        """Test result() handles null result."""
        mock_response = {"id": "test-job", "result": None}

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/",
                json=mock_response,
            )

            result = mock_client.result("test-job")

            assert result == {}

    def test_result_includes_with_result_true_param(self, mock_client):
        """Test result() includes with_result=true parameter."""
        mock_response = {"id": "test-job", "result": "{}"}

        with requests_mock.Mocker() as mocker:
            mock_request = mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/",
                json=mock_response,
            )

            mock_client.result("test-job")

            assert mock_request.last_request.qs["with_result"] == ["true"]


class TestLogsMethod:
    """Test ServerlessClient.logs() method."""

    def test_logs_returns_log_string(self, mock_client):
        """Test logs() returns log string."""
        mock_response = {"logs": "Log line 1\nLog line 2\nLog line 3"}

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/logs/",
                json=mock_response,
            )

            logs = mock_client.logs("test-job")

            assert logs == "Log line 1\nLog line 2\nLog line 3"

    def test_logs_with_empty_logs(self, mock_client):
        """Test logs() handles empty logs."""
        mock_response = {"logs": ""}

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/logs/",
                json=mock_response,
            )

            logs = mock_client.logs("test-job")

            assert logs == ""

    def test_logs_with_missing_logs_key(self, mock_client):
        """Test logs() handles missing logs key."""
        mock_response = {}

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/logs/",
                json=mock_response,
            )

            logs = mock_client.logs("test-job")

            assert logs is None


class TestProviderLogsMethod:
    """Test ServerlessClient.provider_logs() method."""

    def test_provider_logs_returns_log_string(self, mock_client):
        """Test provider_logs() returns log string."""
        mock_response = {"logs": "Provider log 1\nProvider log 2"}

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/provider-logs/",
                json=mock_response,
            )

            logs = mock_client.provider_logs("test-job")

            assert logs == "Provider log 1\nProvider log 2"


class TestRuntimeJobsMethod:
    """Test ServerlessClient.runtime_jobs() method."""

    def test_runtime_jobs_returns_all_jobs(self, mock_client):
        """Test runtime_jobs() returns all runtime job IDs."""
        mock_response = {
            "runtime_jobs": [
                {"runtime_job": "job-1", "runtime_session": "session-1"},
                {"runtime_job": "job-2", "runtime_session": "session-1"},
                {"runtime_job": "job-3", "runtime_session": "session-2"},
            ]
        }

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/runtime_jobs/",
                json=mock_response,
            )

            runtime_jobs = mock_client.runtime_jobs("test-job")

            assert len(runtime_jobs) == 3
            assert runtime_jobs == ["job-1", "job-2", "job-3"]

    def test_runtime_jobs_filtered_by_session(self, mock_client):
        """Test runtime_jobs() filters by session ID."""
        mock_response = {
            "runtime_jobs": [
                {"runtime_job": "job-1", "runtime_session": "session-1"},
                {"runtime_job": "job-2", "runtime_session": "session-1"},
                {"runtime_job": "job-3", "runtime_session": "session-2"},
            ]
        }

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/runtime_jobs/",
                json=mock_response,
            )

            runtime_jobs = mock_client.runtime_jobs("test-job", runtime_session="session-1")

            assert len(runtime_jobs) == 2
            assert runtime_jobs == ["job-1", "job-2"]

    def test_runtime_jobs_empty_results(self, mock_client):
        """Test runtime_jobs() with empty results."""
        mock_response = {"runtime_jobs": []}

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/runtime_jobs/",
                json=mock_response,
            )

            runtime_jobs = mock_client.runtime_jobs("test-job")

            assert runtime_jobs == []


class TestRuntimeSessionsMethod:
    """Test ServerlessClient.runtime_sessions() method."""

    def test_runtime_sessions_returns_unique_sessions(self, mock_client):
        """Test runtime_sessions() returns unique session IDs."""
        mock_response = {
            "runtime_jobs": [
                {"runtime_job": "job-1", "runtime_session": "session-1"},
                {"runtime_job": "job-2", "runtime_session": "session-1"},
                {"runtime_job": "job-3", "runtime_session": "session-2"},
                {"runtime_job": "job-4", "runtime_session": "session-2"},
            ]
        }

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/runtime_jobs/",
                json=mock_response,
            )

            sessions = mock_client.runtime_sessions("test-job")

            assert len(sessions) == 2
            assert sessions == ["session-1", "session-2"]

    def test_runtime_sessions_sorted(self, mock_client):
        """Test runtime_sessions() returns sorted session IDs."""
        mock_response = {
            "runtime_jobs": [
                {"runtime_job": "job-1", "runtime_session": "session-3"},
                {"runtime_job": "job-2", "runtime_session": "session-1"},
                {"runtime_job": "job-3", "runtime_session": "session-2"},
            ]
        }

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/runtime_jobs/",
                json=mock_response,
            )

            sessions = mock_client.runtime_sessions("test-job")

            assert sessions == ["session-1", "session-2", "session-3"]

    def test_runtime_sessions_filters_none_values(self, mock_client):
        """Test runtime_sessions() filters out None session values."""
        mock_response = {
            "runtime_jobs": [
                {"runtime_job": "job-1", "runtime_session": "session-1"},
                {"runtime_job": "job-2", "runtime_session": None},
                {"runtime_job": "job-3"},
            ]
        }

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/runtime_jobs/",
                json=mock_response,
            )

            sessions = mock_client.runtime_sessions("test-job")

            assert sessions == ["session-1"]


class TestFilteredLogsMethod:
    """Test ServerlessClient.filtered_logs() method."""

    def test_filtered_logs_with_include_pattern(self, mock_client):
        """Test filtered_logs() with include pattern."""
        mock_response = {"logs": "Line 1: INFO message\nLine 2: ERROR message\nLine 3: INFO message\n"}

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/logs/",
                json=mock_response,
            )

            filtered = mock_client.filtered_logs("test-job", include="ERROR")

            assert filtered == "Line 2: ERROR message\n"

    def test_filtered_logs_with_exclude_pattern(self, mock_client):
        """Test filtered_logs() with exclude pattern."""
        mock_response = {"logs": "Line 1: INFO message\nLine 2: ERROR message\nLine 3: INFO message\n"}

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/logs/",
                json=mock_response,
            )

            filtered = mock_client.filtered_logs("test-job", exclude="ERROR")

            assert filtered == "Line 1: INFO message\nLine 3: INFO message\n"

    def test_filtered_logs_with_include_and_exclude(self, mock_client):
        """Test filtered_logs() with both include and exclude patterns."""
        mock_response = {"logs": "Line 1: INFO message\nLine 2: ERROR critical\nLine 3: ERROR warning\n"}

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/logs/",
                json=mock_response,
            )

            filtered = mock_client.filtered_logs("test-job", include="ERROR", exclude="warning")

            assert filtered == "Line 2: ERROR critical\n"

    def test_filtered_logs_without_patterns(self, mock_client):
        """Test filtered_logs() without any patterns returns all logs."""
        mock_response = {"logs": "Line 1\nLine 2\nLine 3\n"}

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/logs/",
                json=mock_response,
            )

            filtered = mock_client.filtered_logs("test-job")

            assert filtered == "Line 1\nLine 2\nLine 3\n"

    def test_filtered_logs_with_regex_pattern(self, mock_client):
        """Test filtered_logs() with regex pattern."""
        mock_response = {"logs": "2024-01-01 INFO: message\n2024-01-02 ERROR: problem\n2024-01-03 INFO: ok\n"}

        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/logs/",
                json=mock_response,
            )

            filtered = mock_client.filtered_logs("test-job", include=r"\d{4}-\d{2}-\d{2} ERROR")
            assert filtered == "2024-01-02 ERROR: problem\n"


class TestComputeProfile:
    """Test compute_profile functionality."""

    def test_run_with_compute_profile(self, mock_client):
        """Test run() passes compute_profile to API and Job property works."""
        mock_response = {"id": "test-job-id", "status": "QUEUED", "compute_profile": "gx3d-24x120x1a100p"}

        with requests_mock.Mocker() as mocker:
            mock_request = mocker.post(
                "https://test-host.com/api/v1/programs/run/",
                json=mock_response,
            )
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job-id/",
                json=mock_response,
            )

            job = mock_client.run(program="test-program", compute_profile="gx3d-24x120x1a100p")

            # Verify client sent compute_profile to API
            request_data = json.loads(mock_request.last_request.text)
            assert "compute_profile" in request_data
            assert request_data["compute_profile"] == "gx3d-24x120x1a100p"

            # Verify Job.compute_profile property works
            assert job.compute_profile == "gx3d-24x120x1a100p"

    def test_run_without_compute_profile(self, mock_client):
        """Test run() without compute_profile - backend applies default."""
        # Mock response includes default compute_profile applied by backend
        mock_response = {
            "id": "test-job-id",
            "status": "QUEUED",
            "compute_profile": "cx3d-4x16",  # Default applied by gateway
        }

        with requests_mock.Mocker() as mocker:
            mock_request = mocker.post(
                "https://test-host.com/api/v1/programs/run/",
                json=mock_response,
            )
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job-id/",
                json=mock_response,
            )

            job = mock_client.run(program="test-program")

            # Verify client sent compute_profile as None (backend will apply default)
            request_data = json.loads(mock_request.last_request.text)
            assert request_data["compute_profile"] is None

            # Verify backend applied the default
            assert job.compute_profile == "cx3d-4x16"
