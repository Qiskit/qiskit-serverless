"""Tests for utilities."""
from unittest.mock import MagicMock

from rest_framework.test import APITestCase

from api.utils import build_env_variables, encrypt_string, decrypt_string


class TestUtils(APITestCase):
    """TestUtils."""

    def test_build_env_for_job(self):
        """Tests building of env vars for job."""

        request = MagicMock()
        request.auth.token.decode.return_value = "42"
        job = MagicMock()
        job.id = "42"
        program = MagicMock()
        program.arguments = {"answer": 42}
        env_vars = build_env_variables(request=request, job=job, program=program)
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
                request=request, job=job, program=program
            )
            self.assertEqual(
                decrypt_string(env_vars_with_qiskit_runtime["QISKIT_IBM_TOKEN"]), "42"
            )
            del env_vars_with_qiskit_runtime["QISKIT_IBM_TOKEN"]

            expecting = {
                "ENV_JOB_GATEWAY_TOKEN": "42",
                "ENV_JOB_GATEWAY_HOST": "http://localhost:8000",
                "ENV_JOB_ID_GATEWAY": "42",
                "ENV_JOB_ARGUMENTS": {"answer": 42},
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
