"""Tests job."""
import os
from unittest import TestCase
from unittest.mock import MagicMock

import numpy as np
import requests_mock

from qiskit.circuit.random import random_circuit

from qiskit_serverless.core.constants import (
    ENV_JOB_GATEWAY_HOST,
    ENV_JOB_ID_GATEWAY,
    ENV_JOB_GATEWAY_TOKEN,
)
from qiskit_serverless.core.job import save_result, GatewayJobClient


class TestJob(TestCase):
    """TestJob."""

    def test_save_result(self):
        """Tests job save result."""

        os.environ[ENV_JOB_GATEWAY_HOST] = "https://awesome-tests.com/"
        os.environ[ENV_JOB_ID_GATEWAY] = "42"
        os.environ[ENV_JOB_GATEWAY_TOKEN] = "awesome-token"

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
            self.assertTrue(result)

    def test_filtered_logs(self):
        """Tests job filtered log."""
        client = GatewayJobClient("host", "token", "version")
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
