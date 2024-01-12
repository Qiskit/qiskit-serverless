"""Tests for utilities."""
from unittest.mock import MagicMock

from rest_framework.test import APITestCase

from api.utils import (
    build_env_variables,
    encrypt_string,
    decrypt_string,
    encrypt_env_vars,
    decrypt_env_vars,
    check_logs,
)


class TestUtils(APITestCase):
    """TestUtils."""

    def test_build_env_for_job(self):
        """Tests building of env vars for job."""

        token = "42"
        job = MagicMock()
        job.id = "42"
        env_vars = build_env_variables(token=token, job=job, arguments={"answer": 42})
        self.assertEqual(
            env_vars,
            {
                "ENV_JOB_GATEWAY_TOKEN": "42",
                "ENV_JOB_GATEWAY_HOST": "http://localhost:8000",
                "ENV_JOB_ID_GATEWAY": "42",
                "ENV_JOB_ARGUMENTS": {"answer": 42},
            },
        )

        with self.settings(
            SETTINGS_AUTH_MECHANISM="custom_token", SECRET_KEY="super-secret"
        ):
            env_vars_with_qiskit_runtime = build_env_variables(
                token=token, job=job, arguments={"answer": 42}
            )
            expecting = {
                "ENV_JOB_GATEWAY_TOKEN": "42",
                "ENV_JOB_GATEWAY_HOST": "http://localhost:8000",
                "ENV_JOB_ID_GATEWAY": "42",
                "ENV_JOB_ARGUMENTS": {"answer": 42},
                "QISKIT_IBM_TOKEN": "42",
                "QISKIT_IBM_CHANNEL": "ibm_quantum",
                "QISKIT_IBM_URL": "https://auth.quantum-computing.ibm.com/api",
            }
            self.assertEqual(env_vars_with_qiskit_runtime, expecting)

    def test_encryption(self):
        """Tests encryption utils."""
        string = "awesome string"
        with self.settings(SECRET_KEY="django-super-secret"):
            encrypted_string = encrypt_string(string)
            decrypted_string = decrypt_string(encrypted_string)
            self.assertEqual(string, decrypted_string)

    def test_env_vars_encryption(self):
        """Tests env vars encryption."""
        with self.settings(SECRET_KEY="super-secret"):
            env_vars_with_qiskit_runtime = {
                "ENV_JOB_GATEWAY_TOKEN": "42",
                "ENV_JOB_GATEWAY_HOST": "http://localhost:8000",
                "ENV_JOB_ID_GATEWAY": "42",
                "ENV_JOB_ARGUMENTS": {"answer": 42},
                "QISKIT_IBM_TOKEN": "42",
                "QISKIT_IBM_CHANNEL": "ibm_quantum",
                "QISKIT_IBM_URL": "https://auth.quantum-computing.ibm.com/api",
            }
            encrypted_env_vars = encrypt_env_vars(env_vars_with_qiskit_runtime)
            self.assertFalse(encrypted_env_vars["QISKIT_IBM_TOKEN"] == "42")
            self.assertFalse(encrypted_env_vars["ENV_JOB_GATEWAY_TOKEN"] == "42")
            self.assertEqual(
                env_vars_with_qiskit_runtime, decrypt_env_vars(encrypted_env_vars)
            )

    # TODO: concatenate tests for check_logs?
    # TODO: add a test in test_commands.py?
    def test_check_empty_logs(self):
        """Test error notification for failed and empty logs."""
        job = MagicMock()
        job.id = "42"
        job.status = "FAILED"
        logs = check_logs(logs="", job=job)
        self.assertEqual(logs, "Job 42 failed due to an internal error.")
        self.assertFalse(logs == "")

    def test_check_non_empty_logs(self):
        """Test logs checker for non empty logs."""
        job = MagicMock()
        job.id = "42"
        job.status = "FAILED"
        logs = check_logs(logs="awsome logs", job=job)
        self.assertEqual(logs, "awsome logs")
        self.assertFalse(logs == "Job 42 failed due to an internal error.")
