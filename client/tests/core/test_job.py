"""Tests job."""

# pylint: disable=too-few-public-methods
import os
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
    ENV_ACCESS_TRIAL,
)
from qiskit_serverless.core.job import (
    is_running_in_serverless,
    save_result,
    is_trial,
    update_status,
)


# pylint: disable=redefined-outer-name
@pytest.fixture()
def job_env_variables(monkeypatch):
    """Fixture to set mock job environment variables."""
    # Inspired by https://stackoverflow.com/a/77256931/1558890
    with patch.dict(os.environ, clear=True):
        monkeypatch.setenv(ENV_JOB_GATEWAY_HOST, "https://awesome-tests.com/")
        monkeypatch.setenv(ENV_JOB_ID_GATEWAY, "42")
        monkeypatch.setenv(ENV_JOB_GATEWAY_TOKEN, "awesome-token")
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
        monkeypatch.setenv(ENV_ACCESS_TRIAL, "True")
        yield  # Restore the environment after the test runs


class ResponseMock:
    """Utility class to mock request.get response with a json"""

    ok = True
    text = "{}"


class TestJob:
    """TestJob."""

    def test_save_result(self, job_env_variables):
        """Tests job save result."""
        _ = job_env_variables

        url = (
            f"{os.environ.get(ENV_JOB_GATEWAY_HOST)}/"
            f"api/v1/jobs/{os.environ.get(ENV_JOB_ID_GATEWAY)}/result/"
        )
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
        client = ServerlessClient(host="host", token="token", version="version")
        client.logs = MagicMock(
            return_value="This is the line 1\nThis is the second line\nOK.  This is the last line.\n",  # pylint: disable=line-too-long
        )
        assert "OK.  This is the last line.\n" == client.filtered_logs(
            "id", include="the.+a.+l"
        )
        assert "This is the line 1\nThis is the second line\n" == client.filtered_logs(
            "id", exclude="the.+a.+l"
        )
        assert "This is the line 1\n" == client.filtered_logs(
            "id", include="This is the l.+", exclude="the.+a.+l"
        )


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
