"""Tests for utilities."""

from unittest.mock import MagicMock

from rest_framework.test import APITestCase

from api.domain.authentication.channel import Channel
from api.utils import (
    build_env_variables,
    encrypt_string,
    decrypt_string,
    encrypt_env_vars,
    decrypt_env_vars,
    check_logs,
    remove_duplicates_from_list,
)


class TestUtils(APITestCase):
    """TestUtils."""

    def test_ibm_quantum_env_var_build(self):
        """This test is to test the env_vars for an IBM Quantum authentication process."""

        with self.settings(SETTINGS_AUTH_MECHANISM="custom_token"):
            channel = Channel.IBM_QUANTUM
            token = "an_awesome_token"
            job = MagicMock()
            job.id = "42"
            trial = False
            arguments = "{}"
            instance = None

            env_vars = build_env_variables(
                channel=channel,
                token=token,
                job=job,
                trial_mode=trial,
                args=arguments,
                instance=instance,
            )

            self.assertEqual(
                env_vars,
                {
                    "ENV_JOB_GATEWAY_TOKEN": "an_awesome_token",
                    "ENV_JOB_GATEWAY_HOST": "http://localhost:8000",
                    "ENV_JOB_ID_GATEWAY": "42",
                    "ENV_JOB_ARGUMENTS": "{}",
                    "ENV_ACCESS_TRIAL": "False",
                    "QISKIT_IBM_TOKEN": "an_awesome_token",
                    "QISKIT_IBM_CHANNEL": "ibm_quantum",
                    "QISKIT_IBM_URL": "https://auth.quantum.ibm.com/api",
                },
            )

    def test_ibm_cloud_env_var_build(self):
        """This test is to test the env_vars for an IBM Cloud authentication process."""

        with self.settings(SETTINGS_AUTH_MECHANISM="custom_token"):
            channel = Channel.IBM_QUANTUM_PLATFORM
            token = "an_awesome_api_key"
            job = MagicMock()
            job.id = "42"
            trial = False
            arguments = "{}"
            instance = "an_awesome_crn"

            env_vars = build_env_variables(
                channel=channel,
                token=token,
                job=job,
                trial_mode=trial,
                args=arguments,
                instance=instance,
            )

            self.assertEqual(
                env_vars,
                {
                    "ENV_JOB_GATEWAY_TOKEN": "an_awesome_api_key",
                    "ENV_JOB_GATEWAY_INSTANCE": "an_awesome_crn",
                    "ENV_JOB_GATEWAY_HOST": "http://localhost:8000",
                    "ENV_JOB_ID_GATEWAY": "42",
                    "ENV_JOB_ARGUMENTS": "{}",
                    "ENV_ACCESS_TRIAL": "False",
                    "QISKIT_IBM_TOKEN": "an_awesome_api_key",
                    "QISKIT_IBM_CHANNEL": "ibm_quantum_platform",
                    "QISKIT_IBM_INSTANCE": "an_awesome_crn",
                    "QISKIT_IBM_URL": "https://cloud.ibm.com",
                },
            )

    def test_local_env_var_build(self):
        """This test is to test the env_vars for a local authentication process."""

        with self.settings(SETTINGS_AUTH_MECHANISM="mock_token"):
            channel = Channel.LOCAL
            token = "mock_token"
            job = MagicMock()
            job.id = "42"
            trial = False
            arguments = "{}"
            instance = None

            env_vars = build_env_variables(
                channel=channel,
                token=token,
                job=job,
                trial_mode=trial,
                args=arguments,
                instance=instance,
            )

            self.assertEqual(
                env_vars,
                {
                    "ENV_JOB_GATEWAY_TOKEN": "mock_token",
                    "ENV_JOB_GATEWAY_HOST": "http://localhost:8000",
                    "ENV_JOB_ID_GATEWAY": "42",
                    "ENV_JOB_ARGUMENTS": "{}",
                    "ENV_ACCESS_TRIAL": "False",
                    "QISKIT_IBM_TOKEN": "mock_token",
                    "QISKIT_IBM_CHANNEL": "local",
                    "QISKIT_IBM_URL": "https://cloud.ibm.com",
                },
            )

    def test_trial_mode_env_var_build(self):
        """This test will verify that the environment variables are correct with trial mode activated."""

        with self.settings(SETTINGS_AUTH_MECHANISM="mock_token"):
            channel = Channel.LOCAL
            token = "mock_token"
            job = MagicMock()
            job.id = "42"
            trial = True
            arguments = "{}"
            instance = None

            env_vars = build_env_variables(
                channel=channel,
                token=token,
                job=job,
                trial_mode=trial,
                args=arguments,
                instance=instance,
            )

            self.assertEqual(
                env_vars,
                {
                    "ENV_JOB_GATEWAY_TOKEN": "mock_token",
                    "ENV_JOB_GATEWAY_HOST": "http://localhost:8000",
                    "ENV_JOB_ID_GATEWAY": "42",
                    "ENV_JOB_ARGUMENTS": "{}",
                    "ENV_ACCESS_TRIAL": "True",
                    "QISKIT_IBM_TOKEN": "mock_token",
                    "QISKIT_IBM_CHANNEL": "local",
                    "QISKIT_IBM_URL": "https://cloud.ibm.com",
                },
            )

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
                "QISKIT_IBM_URL": "https://cloud.ibm.com",
            }
            encrypted_env_vars = encrypt_env_vars(env_vars_with_qiskit_runtime)
            self.assertFalse(encrypted_env_vars["QISKIT_IBM_TOKEN"] == "42")
            self.assertFalse(encrypted_env_vars["ENV_JOB_GATEWAY_TOKEN"] == "42")
            self.assertEqual(
                env_vars_with_qiskit_runtime, decrypt_env_vars(encrypted_env_vars)
            )

    def test_check_empty_logs(self):
        """Test error notification for failed and empty logs."""
        job = MagicMock()
        job.id = "42"
        job.status = "FAILED"
        logs = check_logs(logs="", job=job)
        self.assertEqual(logs, "Job 42 failed due to an internal error.")

    def test_check_non_empty_logs(self):
        """Test logs checker for non empty logs."""
        job = MagicMock()
        job.id = "42"
        job.status = "FAILED"
        logs = check_logs(logs="awsome logs", job=job)
        self.assertEqual(logs, "awsome logs")

    def test_remove_duplicates_from_list(self):
        list_with_duplicates = ["value_two", "value_one", "value_two"]
        test_list = ["value_two", "value_one"]
        self.assertListEqual(
            test_list, remove_duplicates_from_list(list_with_duplicates)
        )
