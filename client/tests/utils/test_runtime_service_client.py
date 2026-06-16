# This code is a Qiskit project.
#
# (C) Copyright IBM 2024.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Tests for runtime_service_client utilities."""

from unittest.mock import patch, MagicMock

import requests

from qiskit_serverless.utils.runtime_service_client import associate_runtime_job_with_serverless_job
from qiskit_serverless.core.constants import (
    ENV_JOB_GATEWAY_HOST,
    ENV_JOB_GATEWAY_TOKEN,
    ENV_JOB_ID_GATEWAY,
)

_ENV = {
    ENV_JOB_GATEWAY_HOST: "http://gateway:8000",
    ENV_JOB_GATEWAY_TOKEN: "test-token",
    ENV_JOB_ID_GATEWAY: "job-123",
}


class TestAssociateRuntimeJobWithServerlessJob:
    """Tests for associate_runtime_job_with_serverless_job."""

    def test_returns_false_when_token_missing(self):
        """Returns False immediately when ENV_JOB_GATEWAY_TOKEN is not set."""
        with patch.dict("os.environ", {}, clear=True):
            result = associate_runtime_job_with_serverless_job("runtime-job-1")
        assert result is False

    def test_returns_true_on_success(self):
        """Returns True when the gateway POST succeeds."""
        mock_response = MagicMock()
        mock_response.ok = True

        with patch.dict("os.environ", _ENV), patch("requests.post", return_value=mock_response) as mock_post:
            result = associate_runtime_job_with_serverless_job("runtime-job-1")

        assert result is True
        mock_post.assert_called_once()

    def test_returns_false_on_http_error(self):
        """Returns False when the gateway returns a non-OK response."""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.text = "Internal Server Error"

        with patch.dict("os.environ", _ENV), patch("requests.post", return_value=mock_response):
            result = associate_runtime_job_with_serverless_job("runtime-job-1")

        assert result is False

    def test_returns_false_on_connection_error(self):
        """Returns False instead of raising when the gateway is unreachable."""
        with patch.dict("os.environ", _ENV), patch(
            "requests.post", side_effect=requests.exceptions.ConnectionError("refused")
        ):
            result = associate_runtime_job_with_serverless_job("runtime-job-1")

        assert result is False

    def test_returns_false_on_timeout(self):
        """Returns False instead of raising when the request times out."""
        with patch.dict("os.environ", _ENV), patch(
            "requests.post", side_effect=requests.exceptions.Timeout("timed out")
        ):
            result = associate_runtime_job_with_serverless_job("runtime-job-1")

        assert result is False

    def test_posts_to_correct_url(self):
        """Verifies the request targets the right endpoint."""
        mock_response = MagicMock()
        mock_response.ok = True

        with patch.dict("os.environ", _ENV), patch("requests.post", return_value=mock_response) as mock_post:
            associate_runtime_job_with_serverless_job("runtime-job-1")

        url = mock_post.call_args[0][0]
        assert "job-123" in url
        assert "runtime_jobs" in url

    def test_passes_session_id(self):
        """Verifies session_id is forwarded in the request body."""
        mock_response = MagicMock()
        mock_response.ok = True

        with patch.dict("os.environ", _ENV), patch("requests.post", return_value=mock_response) as mock_post:
            associate_runtime_job_with_serverless_job("runtime-job-1", session_id="session-abc")

        payload = mock_post.call_args[1]["json"]
        assert payload["runtime_session"] == "session-abc"
