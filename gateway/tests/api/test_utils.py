"""Tests for utilities."""

import pytest
from typing import Union, Literal
from unittest.mock import MagicMock

from core.models import Job, Program
from api.domain.authentication.channel import Channel
from api.utils import (
    build_env_variables,
    remove_duplicates_from_list,
)
from core.utils import (
    encrypt_string,
    decrypt_string,
    encrypt_env_vars,
    decrypt_env_vars,
)


class TestUtils:
    """TestUtils."""

    @staticmethod
    def _create_mock_job(
        job_id: str,
        job_author_username: str,
        program_title: str,
        program_provider: str = None,
        arguments: dict = None,
        runner: Literal[Program.FLEETS, Program.RAY] = Program.FLEETS,
        instances: Union[str, list[str]] = None,
        trial_instances: Union[str, list[str]] = None,
        trial: bool = False,
    ) -> Job:
        """Create a mock job."""
        job = MagicMock()
        job.id = job_id
        job.author.username = job_author_username
        job.program.title = program_title
        if program_provider is None:
            job.program.provider = None
        else:
            job.program.provider.name = program_provider
        job.trial = trial
        job.runner = runner

        if not arguments:
            arguments = {}
        job.arguments = arguments

        if isinstance(instances, str):
            instances = [instances]
        if isinstance(instances, list):
            job.instance_crn = instances

        if isinstance(trial_instances, str):
            trial_instances = [trial_instances]
        if isinstance(instances, list):
            job.trial_instances = trial_instances

        return job

    def test_ibm_cloud_env_var_build(self, settings):
        """This test is to test the env_vars for an IBM Cloud authentication process."""
        settings.SETTINGS_AUTH_MECHANISM = "custom_token"
        channel = Channel.IBM_QUANTUM_PLATFORM
        token = "an_awesome_api_key"
        trial = False
        arguments = "{}"
        instance = "an_awesome_crn"

        job = TestUtils._create_mock_job(
            job_id="42",
            job_author_username="an_awesome_username",
            program_title="an_awesome_program",
            instances=["an_awesome_crn"],
            trial=False,
        )

        env_vars = build_env_variables(
            channel=channel,
            token=token,
            job=job,
            trial_mode=trial,
            args=arguments,
            instance=instance,
        )

        assert env_vars == {
            "ENV_JOB_GATEWAY_TOKEN": "an_awesome_api_key",
            "ENV_JOB_GATEWAY_INSTANCE": "an_awesome_crn",
            "ENV_JOB_GATEWAY_HOST": "http://localhost:8000",
            "ENV_JOB_ID_GATEWAY": "42",
            "ENV_JOB_ARGUMENTS": "{}",
            "ENV_ACCESS_TRIAL": "False",
            "DATA_PATH": "/data",
            "ARGUMENTS_PATH": "/data/arguments/42.json",
            "RESULTS_PATH": "/data/results/42.json",  # This is the container result path.
            "QISKIT_IBM_TOKEN": "an_awesome_api_key",
            "QISKIT_IBM_CHANNEL": "ibm_quantum_platform",
            "QISKIT_IBM_INSTANCE": "an_awesome_crn",
            "QISKIT_IBM_URL": "https://cloud.ibm.com",
        }

    def test_ibm_cloud_local_env_var_build(self, settings):
        """This test is to test the env_vars for an IBM Cloud authentication process."""
        settings.SETTINGS_AUTH_MECHANISM = "custom_token"
        settings.RAY_CLUSTER_MODE_LOCAL = True
        channel = Channel.IBM_QUANTUM_PLATFORM
        token = "an_awesome_api_key"
        trial = False
        arguments = "{}"
        instance = "an_awesome_crn"

        job = TestUtils._create_mock_job(
            job_id="42",
            job_author_username="IBMid-691000IC75",
            program_title="an_awesome_program",
            instances=["an_awesome_crn"],
            trial=False,
        )

        env_vars = build_env_variables(
            channel=channel,
            token=token,
            job=job,
            trial_mode=trial,
            args=arguments,
            instance=instance,
        )

        assert env_vars == {
            "ENV_JOB_GATEWAY_TOKEN": "an_awesome_api_key",
            "ENV_JOB_GATEWAY_INSTANCE": "an_awesome_crn",
            "ENV_JOB_GATEWAY_HOST": "http://localhost:8000",
            "ENV_JOB_ID_GATEWAY": "42",
            "ENV_JOB_ARGUMENTS": "{}",
            "ENV_ACCESS_TRIAL": "False",
            "DATA_PATH": "/data/IBMid-691000IC75",
            "ARGUMENTS_PATH": "/data/IBMid-691000IC75/arguments/42.json",
            "RESULTS_PATH": "/data/IBMid-691000IC75/results/42.json",
            "QISKIT_IBM_TOKEN": "an_awesome_api_key",
            "QISKIT_IBM_CHANNEL": "ibm_quantum_platform",
            "QISKIT_IBM_INSTANCE": "an_awesome_crn",
            "QISKIT_IBM_URL": "https://cloud.ibm.com",
        }

    def test_local_env_var_build(self, settings):
        """This test is to test the env_vars for a local authentication process."""
        settings.SETTINGS_AUTH_MECHANISM = "mock_token"
        settings.RAY_CLUSTER_MODE_LOCAL = True
        channel = Channel.LOCAL
        token = "mock_token"
        trial = False
        arguments = "{}"
        instance = None

        job = TestUtils._create_mock_job(
            job_id="42", job_author_username="IBMid-691000IC75", program_title="an_awesome_program", trial=False
        )

        env_vars = build_env_variables(
            channel=channel,
            token=token,
            job=job,
            trial_mode=trial,
            args=arguments,
            instance=instance,
        )

        assert env_vars == {
            "ENV_JOB_GATEWAY_TOKEN": "mock_token",
            "ENV_JOB_GATEWAY_HOST": "http://localhost:8000",
            "ENV_JOB_ID_GATEWAY": "42",
            "ENV_JOB_ARGUMENTS": "{}",
            "ENV_ACCESS_TRIAL": "False",
            "DATA_PATH": "/data/IBMid-691000IC75",
            "ARGUMENTS_PATH": "/data/IBMid-691000IC75/arguments/42.json",
            "RESULTS_PATH": "/data/IBMid-691000IC75/results/42.json",
            "QISKIT_IBM_TOKEN": "mock_token",
            "QISKIT_IBM_CHANNEL": "local",
            "QISKIT_IBM_URL": "https://cloud.ibm.com",
        }

    def test_ibm_cloud_local_provider_env_var_build(self, settings):
        """Test env_vars for IBM Cloud authentication with provider function in local mode."""
        settings.SETTINGS_AUTH_MECHANISM = "custom_token"
        settings.RAY_CLUSTER_MODE_LOCAL = True
        channel = Channel.IBM_QUANTUM_PLATFORM
        token = "an_awesome_api_key"
        trial = False
        arguments = "{}"
        instance = "an_awesome_crn"

        job = TestUtils._create_mock_job(
            job_id="42",
            job_author_username="IBMid-691000IC75",
            program_title="my-function",
            program_provider="mockprovider",
            instances=["an_awesome_crn"],
            trial=False,
        )

        env_vars = build_env_variables(
            channel=channel,
            token=token,
            job=job,
            trial_mode=trial,
            args=arguments,
            instance=instance,
        )

        assert env_vars == {
            "ENV_JOB_GATEWAY_TOKEN": "an_awesome_api_key",
            "ENV_JOB_GATEWAY_INSTANCE": "an_awesome_crn",
            "ENV_JOB_GATEWAY_HOST": "http://localhost:8000",
            "ENV_JOB_ID_GATEWAY": "42",
            "ENV_JOB_ARGUMENTS": "{}",
            "ENV_ACCESS_TRIAL": "False",
            "DATA_PATH": "/data/IBMid-691000IC75/mockprovider/my-function",
            "ARGUMENTS_PATH": "/data/IBMid-691000IC75/mockprovider/my-function/arguments/42.json",
            "RESULTS_PATH": "/data/IBMid-691000IC75/mockprovider/my-function/results/42.json",
            "QISKIT_IBM_TOKEN": "an_awesome_api_key",
            "QISKIT_IBM_CHANNEL": "ibm_quantum_platform",
            "QISKIT_IBM_INSTANCE": "an_awesome_crn",
            "QISKIT_IBM_URL": "https://cloud.ibm.com",
        }

    def test_local_provider_env_var_build(self, settings):
        """Test env_vars for local authentication with provider function in local mode."""
        settings.SETTINGS_AUTH_MECHANISM = "mock_token"
        settings.RAY_CLUSTER_MODE_LOCAL = True
        channel = Channel.LOCAL
        token = "mock_token"
        trial = False
        arguments = "{}"
        instance = None

        job = TestUtils._create_mock_job(
            job_id="42",
            job_author_username="IBMid-691000IC75",
            program_title="my-function",
            program_provider="mockprovider",
            trial=trial,
        )

        env_vars = build_env_variables(
            channel=channel,
            token=token,
            job=job,
            trial_mode=trial,
            args=arguments,
            instance=instance,
        )

        assert env_vars == {
            "ENV_JOB_GATEWAY_TOKEN": "mock_token",
            "ENV_JOB_GATEWAY_HOST": "http://localhost:8000",
            "ENV_JOB_ID_GATEWAY": "42",
            "ENV_JOB_ARGUMENTS": "{}",
            "ENV_ACCESS_TRIAL": "False",
            "DATA_PATH": "/data/IBMid-691000IC75/mockprovider/my-function",
            "ARGUMENTS_PATH": "/data/IBMid-691000IC75/mockprovider/my-function/arguments/42.json",
            "RESULTS_PATH": "/data/IBMid-691000IC75/mockprovider/my-function/results/42.json",
            "QISKIT_IBM_TOKEN": "mock_token",
            "QISKIT_IBM_CHANNEL": "local",
            "QISKIT_IBM_URL": "https://cloud.ibm.com",
        }

    def test_trial_mode_env_var_build(self, settings):
        """This test will verify that the environment variables are correct with trial mode activated."""
        settings.SETTINGS_AUTH_MECHANISM = "mock_token"
        channel = Channel.LOCAL
        token = "mock_token"
        job = MagicMock()
        job.id = "42"
        trial = True
        arguments = "{}"
        instance = None

        job = TestUtils._create_mock_job(
            job_id="42", job_author_username="USER", program_title="my-function", instances=instance, trial=trial
        )

        env_vars = build_env_variables(
            channel=channel,
            token=token,
            job=job,
            trial_mode=trial,
            args=arguments,
            instance=instance,
        )

        assert env_vars == {
            "ENV_JOB_GATEWAY_TOKEN": "mock_token",
            "ENV_JOB_GATEWAY_HOST": "http://localhost:8000",
            "ENV_JOB_ID_GATEWAY": "42",
            "ENV_JOB_ARGUMENTS": "{}",
            "ENV_ACCESS_TRIAL": "True",
            "DATA_PATH": "/data",
            "ARGUMENTS_PATH": "/data/arguments/42.json",
            "RESULTS_PATH": "/data/results/42.json",
            "QISKIT_IBM_TOKEN": "mock_token",
            "QISKIT_IBM_CHANNEL": "local",
            "QISKIT_IBM_URL": "https://cloud.ibm.com",
        }

    def test_encryption(self, settings):
        """Tests encryption utils."""
        string = "awesome string"
        settings.SECRET_KEY = "django-super-secret"
        encrypted_string = encrypt_string(string)
        decrypted_string = decrypt_string(encrypted_string)
        assert string == decrypted_string

    def test_env_vars_encryption(self, settings):
        """Tests env vars encryption."""
        settings.SECRET_KEY = "super-secret"
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
        assert not encrypted_env_vars["QISKIT_IBM_TOKEN"] == "42"
        assert not encrypted_env_vars["ENV_JOB_GATEWAY_TOKEN"] == "42"
        assert env_vars_with_qiskit_runtime == decrypt_env_vars(encrypted_env_vars)

    def test_remove_duplicates_from_list(self):
        list_with_duplicates = ["value_two", "value_one", "value_two"]
        test_list = ["value_two", "value_one"]
        assert test_list == remove_duplicates_from_list(list_with_duplicates)
