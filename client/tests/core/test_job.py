"""Tests job."""
import os
from unittest import TestCase

import numpy as np
import requests_mock

from qiskit.circuit.random import random_circuit

from quantum_serverless.core.constants import (
    ENV_JOB_GATEWAY_HOST,
    ENV_JOB_ID_GATEWAY,
    ENV_JOB_GATEWAY_TOKEN,
)
from quantum_serverless.core.job import save_result


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
