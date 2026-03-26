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

"""Tests job."""

# pylint: disable=too-few-public-methods
import os
import json
from unittest.mock import MagicMock, Mock, patch

import numpy as np
import pytest
import requests_mock

from qiskit.circuit.random import random_circuit

from qiskit_serverless import ServerlessClient
from qiskit_serverless.core.constants import (
    ENV_JOB_GATEWAY_HOST,
    ENV_JOB_ID_GATEWAY,
    ENV_JOB_GATEWAY_TOKEN,
    ENV_JOB_GATEWAY_INSTANCE,
    ENV_ACCESS_TRIAL,
)
from qiskit_serverless.core.job import (
    Job,
    is_running_in_serverless,
    save_result,
    is_trial,
    update_status,
    get_runtime_service,
    _map_status_from_serveless,
    _map_status_to_serverless,
)
from qiskit_serverless.core.job_event import JobEvent
from qiskit_serverless.exception import QiskitServerlessException


# pylint: disable=redefined-outer-name
@pytest.fixture()
def job_env_variables(monkeypatch):
    """Fixture to set mock job environment variables."""
    # Inspired by https://stackoverflow.com/a/77256931/1558890
    with patch.dict(os.environ, clear=True):
        monkeypatch.setenv(ENV_JOB_GATEWAY_HOST, "https://awesome-tests.com/")
        monkeypatch.setenv(ENV_JOB_ID_GATEWAY, "42")
        monkeypatch.setenv(ENV_JOB_GATEWAY_TOKEN, "awesome-token")
        monkeypatch.setenv(ENV_JOB_GATEWAY_INSTANCE, "awesome-instance")
        monkeypatch.setenv(ENV_ACCESS_TRIAL, "False")
        yield  # Restore the environment after the test runs


# pylint: disable=redefined-outer-name
@pytest.fixture()
def trial_job_env_variables(monkeypatch):
    """Fixture to set mock job environment variables."""
    # Inspired by https://stackoverflow.com/a/77256931/1558890
    with patch.dict(os.environ, clear=True):
        monkeypatch.setenv(ENV_JOB_GATEWAY_HOST, "https://awesome-tests.com/")
        monkeypatch.setenv(ENV_JOB_ID_GATEWAY, "42")
        monkeypatch.setenv(ENV_JOB_GATEWAY_TOKEN, "awesome-token")
        monkeypatch.setenv(ENV_JOB_GATEWAY_INSTANCE, "awesome-instance")
        monkeypatch.setenv(ENV_ACCESS_TRIAL, "True")
        yield  # Restore the environment after the test runs


class ResponseMock:
    """Utility class to mock request.get response with a json"""

    ok = True
    text = "{}"


class ResponseMockWithRuntimeJobs:
    """Mocked response for runtime_jobs endpoint."""

    ok = True

    def json(self):
        "Serialize mock response"
        return {
            "runtime_jobs": [
                {"runtime_job": "runtime_job_1", "runtime_session": "session_id_1"},
                {"runtime_job": "runtime_job_2", "runtime_session": "session_id_2"},
            ]
        }

    @property
    def text(self):
        "Response text"
        return json.dumps(self.json())


class TestJob:
    """TestJob."""

    def test_save_result(self, job_env_variables):
        """Tests job save result."""
        _ = job_env_variables

        url = f"{os.environ.get(ENV_JOB_GATEWAY_HOST)}/" f"api/v1/jobs/{os.environ.get(ENV_JOB_ID_GATEWAY)}/result/"
        with requests_mock.Mocker() as mocker:
            mocker.post(url)
            result = save_result(
                {
                    "numpy_array": np.random.random((4, 2)),
                    "quantum_circuit": random_circuit(3, 2),
                }
            )
            assert result is True

    @patch("requests.patch", Mock(return_value=ResponseMock()))
    def test_update_sub_status(self, job_env_variables):
        """Tests update sub status."""
        _ = job_env_variables

        result = update_status("MAPPING")
        assert result is True

    @patch("requests.get", Mock(return_value=ResponseMock()))
    def test_filtered_logs(self):
        """Tests job filtered log."""
        client = ServerlessClient(host="host", token="token", instance="instance", version="version")
        client.logs = MagicMock(
            return_value="This is the line 1\nThis is the second line\nOK.  This is the last line.\n",  # pylint: disable=line-too-long
        )
        assert "OK.  This is the last line.\n" == client.filtered_logs("id", include="the.+a.+l")
        assert "This is the line 1\nThis is the second line\n" == client.filtered_logs("id", exclude="the.+a.+l")
        assert "This is the line 1\n" == client.filtered_logs("id", include="This is the l.+", exclude="the.+a.+l")

    @patch("requests.get", Mock(return_value=ResponseMock()))
    def test_error_message(self):
        """Tests job filtered log."""
        client = ServerlessClient(host="host", token="token", instance="instance", version="version")
        client.status = MagicMock(
            return_value="ERROR",
        )
        client.result = MagicMock(
            return_value=(
                '"This is the line \\"1\\"\\n' "This is the second line\\n" 'OK.  This is the last line.\\n"'
            ),
        )
        job = Job(
            job_id="job_id",
            job_service=client,
        )
        assert (
            'This is the line "1"\n' "This is the second line\n" "OK.  This is the last line.\n"
        ) == job.error_message()

    @patch("requests.get", Mock(return_value=ResponseMockWithRuntimeJobs()))
    @patch(
        "qiskit_serverless.core.clients.serverless_client.ServerlessClient._verify_credentials",
        Mock(),
    )
    def test_runtime_sessions(self):
        """Tests runtime session id retrieval for serverless job."""
        client = ServerlessClient(host="host", token="token", instance="instance", version="v1")

        job_id = "8317718f-5c0d-4fb6-9947-72e480b8a348"
        runtime_sessions = client.runtime_sessions(job_id)

        assert len(runtime_sessions) == 2
        assert runtime_sessions == ["session_id_1", "session_id_2"]

    @patch("requests.get", Mock(return_value=ResponseMockWithRuntimeJobs()))
    @patch(
        "qiskit_serverless.core.clients.serverless_client.ServerlessClient._verify_credentials",
        Mock(),
    )
    def test_runtime_jobs(self):
        """Tests runtime job id retrieval for serverless job."""
        client = ServerlessClient(host="host", token="token", instance="instance", version="v1")

        job_id = "8317718f-5c0d-4fb6-9947-72e480b8a348"
        runtime_jobs = client.runtime_jobs(job_id)

        assert len(runtime_jobs) == 2
        assert runtime_jobs == ["runtime_job_1", "runtime_job_2"]

        runtime_sessions = client.runtime_sessions(job_id)
        session_job = client.runtime_jobs(job_id, runtime_sessions[0])
        assert session_job == ["runtime_job_1"]


class TestRunningAsServerlessProgram:
    """Test ``is_running_in_serverless()``."""

    def test_not_running_as_serverless_program(self):
        """Test ``is_running_in_serverless()`` outside a serverless program."""
        assert is_running_in_serverless() is False

    def test_running_as_serverless_program(self, job_env_variables):
        """Test ``is_running_in_serverless()`` in a mocked serverless program."""
        _ = job_env_variables
        assert is_running_in_serverless() is True


class TestRunningInTrialMode:
    """Test ``is_trial()``."""

    def test_not_running_in_trial_mode(self, job_env_variables):
        """Test ``is_trial()`` in a not trial job."""
        _ = job_env_variables
        assert is_trial() is False

    def test_running_in_trial_mode(self, trial_job_env_variables):
        """Test ``is_trial()`` in a trial job."""
        _ = trial_job_env_variables
        assert is_trial() is True


class TestJobResult:
    """Test Job.result() method with various parameters."""

    def test_result_without_wait(self):
        """Test result() without waiting for completion."""
        mock_service = Mock()
        mock_service.result.return_value = {"key": "value"}
        mock_service.status.return_value = Job.SUCCEEDED

        job = Job(job_id="test-job", job_service=mock_service)
        result = job.result(wait=False)

        assert result == {"key": "value"}
        mock_service.result.assert_called_once_with("test-job")

    @patch("time.sleep")
    def test_result_with_wait_until_terminal(self, mock_sleep):
        """Test result() waiting for job to reach terminal state."""
        mock_service = Mock()
        # Simulate job transitioning from RUNNING to SUCCEEDED
        # The while loop calls in_terminal_state() which calls status() internally
        # Just return RUNNING multiple times, then SUCCEEDED
        mock_service.status.return_value = Job.RUNNING

        # After 2 iterations, change to SUCCEEDED
        call_count = 0

        def status_side_effect(_job_id):
            nonlocal call_count
            call_count += 1
            if call_count <= 4:  # First 4 calls return RUNNING
                return Job.RUNNING
            return Job.SUCCEEDED

        mock_service.status.side_effect = status_side_effect
        mock_service.result.return_value = {"result": "success"}

        job = Job(job_id="test-job", job_service=mock_service)
        result = job.result(wait=True, cadence=1, verbose=False)

        assert result == {"result": "success"}
        # Verify sleep was called (exact count depends on implementation details)
        assert mock_sleep.call_count >= 2
        mock_sleep.assert_called_with(1)

    @patch("time.sleep")
    @patch("logging.info")
    def test_result_with_wait_and_verbose(self, mock_log, _mock_sleep):
        """Test result() with verbose logging enabled."""
        mock_service = Mock()
        # Need extra status calls for in_terminal_state checks
        mock_service.status.side_effect = [
            Job.RUNNING,
            Job.RUNNING,  # First iteration
            Job.SUCCEEDED,
            Job.SUCCEEDED,  # Terminal state
        ]
        mock_service.result.return_value = {"result": "success"}

        job = Job(job_id="test-job", job_service=mock_service)
        result = job.result(wait=True, cadence=1, verbose=True)

        assert result == {"result": "success"}
        # Check that verbose logging occurred
        assert mock_log.call_count >= 2  # "Waiting for job result." + count
        mock_log.assert_any_call("Waiting for job result.")

    @patch("time.sleep")
    def test_result_with_maxwait_timeout(self, mock_sleep):
        """Test result() with maxwait parameter timing out."""
        mock_service = Mock()
        # Job never completes within maxwait
        mock_service.status.return_value = Job.RUNNING
        mock_service.result.return_value = None

        job = Job(job_id="test-job", job_service=mock_service)
        _ = job.result(wait=True, cadence=1, verbose=False, maxwait=3)

        # Should stop after maxwait iterations
        assert mock_sleep.call_count == 3
        mock_sleep.assert_called_with(1)

    @patch("time.sleep")
    def test_result_with_custom_cadence(self, mock_sleep):
        """Test result() with custom cadence parameter."""
        mock_service = Mock()
        # Need extra status calls for in_terminal_state checks
        mock_service.status.side_effect = [
            Job.RUNNING,
            Job.RUNNING,  # First iteration
            Job.SUCCEEDED,
            Job.SUCCEEDED,  # Terminal state
        ]
        mock_service.result.return_value = {"result": "success"}

        job = Job(job_id="test-job", job_service=mock_service)
        result = job.result(wait=True, cadence=5, verbose=False)

        assert result == {"result": "success"}
        mock_sleep.assert_called_with(5)

    def test_result_with_json_string_response(self):
        """Test result() decoding JSON string response."""
        mock_service = Mock()
        mock_service.status.return_value = Job.SUCCEEDED
        mock_service.result.return_value = '{"key": "value", "number": 42}'

        job = Job(job_id="test-job", job_service=mock_service)
        result = job.result(wait=False)

        assert result == {"key": "value", "number": 42}

    @patch("logging.warning")
    def test_result_with_invalid_json_string(self, mock_warning):
        """Test result() with invalid JSON string."""
        mock_service = Mock()
        mock_service.status.return_value = Job.SUCCEEDED
        mock_service.result.return_value = "not valid json {"

        job = Job(job_id="test-job", job_service=mock_service)
        result = job.result(wait=False)

        # Should return the string as-is and log warning
        assert result == "not valid json {"
        mock_warning.assert_called_once_with("Error during results decoding.")

    def test_result_raises_exception_on_error_status(self):
        """Test result() raises exception when job status is ERROR."""
        mock_service = Mock()
        mock_service.status.return_value = "ERROR"
        mock_service.result.return_value = "Job execution failed"
        mock_service.events.return_value = []

        job = Job(job_id="test-job", job_service=mock_service)

        with pytest.raises(QiskitServerlessException) as exc_info:
            job.result(wait=False)

        assert "Job execution failed" in str(exc_info.value)

    def test_result_raises_exception_on_error_with_filtered_logs(self):
        """Test result() raises exception with filtered logs when no result."""
        mock_service = Mock()
        mock_service.status.return_value = "ERROR"
        mock_service.result.return_value = None
        mock_service.filtered_logs.return_value = "Error: Something went wrong"
        mock_service.events.return_value = []

        job = Job(job_id="test-job", job_service=mock_service)

        with pytest.raises(QiskitServerlessException) as exc_info:
            job.result(wait=False)

        assert "Error: Something went wrong" in str(exc_info.value)
        mock_service.filtered_logs.assert_called_once()

    def test_result_raises_exception_on_error_status_with_error_event(self):
        """Test result() raises exception when job status is ERROR."""
        mock_service = Mock()
        mock_service.status.return_value = "ERROR"
        mock_service.result.return_value = "Job execution failed"
        mock_service.events.return_value = [
            JobEvent(
                event_type="ERROR",
                origin="MOCK",
                context="Mock",
                created="",
                data={
                    "message": "Job execution failed",
                    "exception": "ServerlessError",
                    "code": "M123",
                    "args": {"my-args": 123},
                },
            )
        ]

        job = Job(job_id="test-job", job_service=mock_service)

        with pytest.raises(QiskitServerlessException) as exc_info:
            job.result(wait=False)

        assert (
            "\n| Message: Job execution failed\n| Code: M123\n| Exception: ServerlessError\n| Details:\n|   - my-args: 123"
            == str(exc_info.value)
        )


class TestJobInTerminalState:
    """Test Job.in_terminal_state() method."""

    @pytest.mark.parametrize(
        "status",
        [
            "CANCELED",
            "DONE",
            "ERROR",
        ],
    )
    def test_in_terminal_state(self, status):
        """Test in_terminal_state() returns True for terminal statuses."""
        mock_service = Mock()
        mock_service.status.return_value = status

        job = Job(job_id="test-job", job_service=mock_service)
        assert job.in_terminal_state() is True

    @pytest.mark.parametrize(
        "status",
        [
            "RUNNING",
            "INITIALIZING",
            "QUEUED",
        ],
    )
    def test_not_in_terminal_state(self, status):
        """Test in_terminal_state() returns False for non-terminal statuses."""
        mock_service = Mock()
        mock_service.status.return_value = status

        job = Job(job_id="test-job", job_service=mock_service)
        assert job.in_terminal_state() is False


class TestGetRuntimeService:
    """Test get_runtime_service() function."""

    @patch("qiskit_serverless.core.job.ServerlessRuntimeService")
    @patch.dict(
        os.environ,
        {
            "QISKIT_IBM_CHANNEL": "ibm_quantum_platform",
            "QISKIT_IBM_INSTANCE": "test-crn",
            "QISKIT_IBM_TOKEN": "test-token",
        },
    )
    def test_get_runtime_service_from_env(self, mock_service_class):
        """Test get_runtime_service() pulls credentials from environment."""
        mock_service_instance = Mock()
        mock_service_class.return_value = mock_service_instance

        service = get_runtime_service()

        assert service is not None
        mock_service_class.assert_called_once_with(
            channel="ibm_quantum_platform",
            instance="test-crn",
            token="test-token",
            url=None,
        )

    @patch("qiskit_serverless.core.job.ServerlessRuntimeService")
    @patch.dict(
        os.environ,
        {
            "QISKIT_IBM_CHANNEL": "ibm_quantum_platform",
            "QISKIT_IBM_INSTANCE": "test-crn",
            "QISKIT_IBM_TOKEN": "test-token",
        },
    )
    def test_get_runtime_service_with_explicit_params(self, mock_service_class):
        """Test get_runtime_service() with explicit parameters."""
        mock_service_instance = Mock()
        mock_service_class.return_value = mock_service_instance

        service = get_runtime_service(
            channel="ibm_cloud",
            token="explicit-token",
            instance="explicit-crn",
            url="https://custom.url",
        )

        assert service is not None
        mock_service_class.assert_called_once_with(
            channel="ibm_cloud",
            instance="explicit-crn",
            token="explicit-token",
            url="https://custom.url",
        )

    @patch("qiskit_serverless.core.job.ServerlessRuntimeService")
    @patch.dict(
        os.environ,
        {
            "QISKIT_IBM_CHANNEL": "ibm_quantum_platform",
            "QISKIT_IBM_INSTANCE": "test-crn",
            "QISKIT_IBM_TOKEN": "test-token",
            "QISKIT_IBM_URL": "https://env.url",
        },
    )
    def test_get_runtime_service_with_url_from_env(self, mock_service_class):
        """Test get_runtime_service() uses URL from environment."""
        mock_service_instance = Mock()
        mock_service_class.return_value = mock_service_instance

        service = get_runtime_service()

        assert service is not None
        mock_service_class.assert_called_once_with(
            channel="ibm_quantum_platform",
            instance="test-crn",
            token="test-token",
            url="https://env.url",
        )

    def test_get_runtime_service_missing_env_raises_error(self):
        """Test get_runtime_service() raises error when env vars missing."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(KeyError):
                get_runtime_service()


class TestStatusMapping:
    """Test status mapping functions."""

    @pytest.mark.parametrize(
        "serverless_status,expected_output",
        [
            (Job.PENDING, "INITIALIZING"),
            (Job.RUNNING, "RUNNING"),
            (Job.STOPPED, "CANCELED"),
            (Job.SUCCEEDED, "DONE"),
            (Job.FAILED, "ERROR"),
            (Job.QUEUED, "QUEUED"),
            (Job.MAPPING, "RUNNING: MAPPING"),
            (Job.OPTIMIZING_HARDWARE, "RUNNING: OPTIMIZING_FOR_HARDWARE"),
            (Job.WAITING_QPU, "RUNNING: WAITING_FOR_QPU"),
            (Job.EXECUTING_QPU, "RUNNING: EXECUTING_QPU"),
            (Job.POST_PROCESSING, "RUNNING: POST_PROCESSING"),
            ("UNKNOWN_STATUS", "UNKNOWN_STATUS"),
        ],
    )
    def test_map_status_from_serverless(self, serverless_status, expected_output):
        """Test mapping status from serverless to external format."""
        assert _map_status_from_serveless(serverless_status) == expected_output

    @pytest.mark.parametrize(
        "external_status,expected_status,expected_sub_status",
        [
            ("INITIALIZING", Job.PENDING, None),
            ("RUNNING", Job.RUNNING, None),
            ("CANCELED", Job.STOPPED, None),
            ("DONE", Job.SUCCEEDED, None),
            ("ERROR", Job.FAILED, None),
            ("QUEUED", Job.QUEUED, None),
            ("RUNNING: MAPPING", Job.RUNNING, Job.MAPPING),
            ("RUNNING: OPTIMIZING_FOR_HARDWARE", Job.RUNNING, Job.OPTIMIZING_HARDWARE),
            ("RUNNING: WAITING_FOR_QPU", Job.RUNNING, Job.WAITING_QPU),
            ("RUNNING: EXECUTING_QPU", Job.RUNNING, Job.EXECUTING_QPU),
            ("RUNNING: POST_PROCESSING", Job.RUNNING, Job.POST_PROCESSING),
            ("UNKNOWN_STATUS", "UNKNOWN_STATUS", None),
        ],
    )
    def test_map_status_to_serverless(self, external_status, expected_status, expected_sub_status):
        """Test mapping status from external format to serverless."""
        status, sub_status = _map_status_to_serverless(external_status)
        assert status == expected_status
        assert sub_status == expected_sub_status


class TestJobMethods:
    """Test Job class methods for canceling, logging, and runtime operations."""

    def test_job_cancel_method(self):
        """Test Job.cancel() method."""
        mock_service = Mock()
        mock_service.stop.return_value = True

        job = Job(job_id="test-job", job_service=mock_service)
        result = job.cancel()

        assert result is True
        mock_service.stop.assert_called_once_with("test-job", service=None)

    def test_job_cancel_with_runtime_service(self):
        """Test Job.cancel() with runtime service parameter."""
        mock_service = Mock()
        mock_runtime_service = Mock()
        mock_service.stop.return_value = True

        job = Job(job_id="test-job", job_service=mock_service)
        result = job.cancel(service=mock_runtime_service)

        assert result is True
        mock_service.stop.assert_called_once_with("test-job", service=mock_runtime_service)

    def test_job_stop_method_deprecated(self):
        """Test Job.stop() method shows deprecation warning."""
        mock_service = Mock()
        mock_service.stop.return_value = True

        job = Job(job_id="test-job", job_service=mock_service)

        with pytest.warns(DeprecationWarning, match="`stop` method has been deprecated"):
            result = job.stop()

        assert result is True

    def test_job_logs_method(self):
        """Test Job.logs() method."""
        mock_service = Mock()
        mock_service.logs.return_value = "Log line 1\nLog line 2\n"

        job = Job(job_id="test-job", job_service=mock_service)
        logs = job.logs()

        assert logs == "Log line 1\nLog line 2\n"
        mock_service.logs.assert_called_once_with("test-job")

    def test_job_provider_logs_method(self):
        """Test Job.provider_logs() method."""
        mock_service = Mock()
        mock_service.provider_logs.return_value = "Provider log 1\nProvider log 2\n"

        job = Job(job_id="test-job", job_service=mock_service)
        logs = job.provider_logs()

        assert logs == "Provider log 1\nProvider log 2\n"
        mock_service.provider_logs.assert_called_once_with("test-job")

    def test_job_runtime_jobs_method(self):
        """Test Job.runtime_jobs() method."""
        mock_service = Mock()
        mock_service.runtime_jobs.return_value = ["job1", "job2"]

        job = Job(job_id="test-job", job_service=mock_service)
        runtime_jobs = job.runtime_jobs()

        assert runtime_jobs == ["job1", "job2"]
        mock_service.runtime_jobs.assert_called_once_with("test-job", runtime_session=None)

    def test_job_runtime_jobs_with_session(self):
        """Test Job.runtime_jobs() with session parameter."""
        mock_service = Mock()
        mock_service.runtime_jobs.return_value = ["job1"]

        job = Job(job_id="test-job", job_service=mock_service)
        runtime_jobs = job.runtime_jobs(runtime_session="session-123")

        assert runtime_jobs == ["job1"]
        mock_service.runtime_jobs.assert_called_once_with("test-job", runtime_session="session-123")

    def test_job_runtime_sessions_method(self):
        """Test Job.runtime_sessions() method."""
        mock_service = Mock()
        mock_service.runtime_sessions.return_value = ["session1", "session2"]

        job = Job(job_id="test-job", job_service=mock_service)
        sessions = job.runtime_sessions()

        assert sessions == ["session1", "session2"]
        mock_service.runtime_sessions.assert_called_once_with("test-job")

    def test_job_filtered_logs_method(self):
        """Test Job.filtered_logs() method."""
        mock_service = Mock()
        mock_service.filtered_logs.return_value = "Filtered log line\n"

        job = Job(job_id="test-job", job_service=mock_service)
        logs = job.filtered_logs(include="pattern", exclude="other")

        assert logs == "Filtered log line\n"
        mock_service.filtered_logs.assert_called_once_with(job_id="test-job", include="pattern", exclude="other")

    def test_job_status_method(self):
        """Test Job.status() method."""
        mock_service = Mock()
        mock_service.status.return_value = Job.RUNNING

        job = Job(job_id="test-job", job_service=mock_service)
        status = job.status()

        assert status == "RUNNING"
        mock_service.status.assert_called_once_with("test-job")

    def test_job_repr(self):
        """Test Job.__repr__() method."""
        mock_service = Mock()
        job = Job(job_id="test-job-123", job_service=mock_service)

        assert repr(job) == "<Job | test-job-123>"

    def test_job_with_raw_data(self):
        """Test Job initialization with raw_data."""
        mock_service = Mock()
        raw_data = {"key": "value", "status": "RUNNING"}

        job = Job(job_id="test-job", job_service=mock_service, raw_data=raw_data)

        assert job.raw_data == raw_data
        assert job.job_id == "test-job"
