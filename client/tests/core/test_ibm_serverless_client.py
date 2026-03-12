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

"""Test IBMServerlessClient."""

import uuid
import unittest
import tempfile
from unittest.mock import patch

from qiskit_serverless import IBMServerlessClient
from qiskit_serverless.core.enums import Channel


class TestIBMServerlessClient(unittest.TestCase):
    """Unit tests for IBMServerlessClient."""

    @patch("qiskit_serverless.core.clients.serverless_client.ServerlessClient._verify_credentials")
    @patch("qiskit_ibm_runtime.accounts.management._DEFAULT_ACCOUNT_CONFIG_JSON_FILE")
    def test_init(self, mock_file_path, mock_verify_credentials):
        """Test __init__ with an explicit token, instance and host"""

        # Mock ServerlessClient credential verification
        mock_verify_credentials.return_value = None

        use_host = "http://other.host"
        use_token = "my_token"
        use_instance = "my_instance"
        use_channel = Channel.IBM_QUANTUM_PLATFORM.value

        # Replace the _DEFAULT_ACCOUNT_CONFIG_JSON_FILE path with a temporary file
        with tempfile.NamedTemporaryFile() as temp_file:
            mock_file_path.return_value = temp_file.name

        client = IBMServerlessClient(token=use_token, instance=use_instance, channel=use_channel, host=use_host)

        assert client.host == use_host
        assert client.channel == use_channel
        assert client.instance == use_instance
        assert client.token == use_token

    @patch("qiskit_serverless.core.clients.serverless_client.ServerlessClient._verify_credentials")
    @patch("qiskit_ibm_runtime.accounts.management._DEFAULT_ACCOUNT_CONFIG_JSON_FILE")
    def test_save_load_account(self, mock_file_path, mock_verify_credentials):
        """Test saving and loading accounts with the IBMServerlessClient."""

        # Mock ServerlessClient credential verification
        mock_verify_credentials.return_value = None

        # Save config in a temporary file
        with tempfile.NamedTemporaryFile() as temp_file:
            mock_file_path.return_value = temp_file.name

        channels_to_test = [
            Channel.IBM_CLOUD.value,
            Channel.IBM_QUANTUM_PLATFORM.value,
        ]

        instances_to_test = [
            "dummy_hub/dummy_group/dummy_project",
            "dummy_crn",
            "dummy_crn",
        ]
        for use_channel, use_instance in zip(channels_to_test, instances_to_test):
            use_token = "save_token"
            use_name = f"test_save_account_{uuid.uuid4().hex}"
            with self.subTest(use_channel=use_channel):
                IBMServerlessClient.save_account(
                    token=use_token,
                    name=use_name,
                    instance=use_instance,
                    channel=use_channel,
                )
                client = IBMServerlessClient(name=use_name)
                assert client.account.channel == use_channel
                assert client.account.token == use_token
                assert client.account.instance == use_instance

    def test_ibm_quantum_channel(self):
        """Test error raised when initializing account with `ibm_quantum` channel."""
        import pytest

        use_channel = "ibm_quantum"
        use_instance = "h/g/p"
        use_token = "save_token"

        with pytest.raises(ValueError, match=r"Your channel value is not correct"):
            IBMServerlessClient(channel=use_channel, instance=use_instance, token=use_token)

    @patch("qiskit_serverless.core.clients.serverless_client.ServerlessClient._verify_credentials")
    @patch("qiskit_ibm_runtime.accounts.management._DEFAULT_ACCOUNT_CONFIG_JSON_FILE")
    def test_channel_defaults_to_ibm_quantum_platform_when_none(self, mock_file_path, mock_verify):
        """Test that channel defaults to IBM_QUANTUM_PLATFORM when None is provided."""
        mock_verify.return_value = None

        with tempfile.NamedTemporaryFile() as temp_file:
            mock_file_path.return_value = temp_file.name

            client = IBMServerlessClient(
                token="test_token", instance="test_instance", channel=None  # Explicitly pass None
            )

            assert client.channel == Channel.IBM_QUANTUM_PLATFORM.value
            assert client.account.channel == Channel.IBM_QUANTUM_PLATFORM.value

    @patch("qiskit_serverless.core.clients.serverless_client.ServerlessClient._verify_credentials")
    @patch("qiskit_ibm_runtime.accounts.management._DEFAULT_ACCOUNT_CONFIG_JSON_FILE")
    def test_channel_defaults_to_ibm_quantum_platform_when_omitted(self, mock_file_path, mock_verify):
        """Test that channel defaults to IBM_QUANTUM_PLATFORM when omitted."""
        mock_verify.return_value = None

        with tempfile.NamedTemporaryFile() as temp_file:
            mock_file_path.return_value = temp_file.name

            client = IBMServerlessClient(
                token="test_token",
                instance="test_instance",
                # channel parameter omitted
            )

            assert client.channel == Channel.IBM_QUANTUM_PLATFORM.value
            assert client.account.channel == Channel.IBM_QUANTUM_PLATFORM.value

    @patch("qiskit_serverless.core.clients.serverless_client.ServerlessClient._verify_credentials")
    @patch("qiskit_ibm_runtime.accounts.management._DEFAULT_ACCOUNT_CONFIG_JSON_FILE")
    def test_channel_respects_explicit_ibm_cloud_value(self, mock_file_path, mock_verify):
        """Test that explicitly provided IBM_CLOUD channel is preserved."""
        mock_verify.return_value = None

        with tempfile.NamedTemporaryFile() as temp_file:
            mock_file_path.return_value = temp_file.name

            client = IBMServerlessClient(token="test_token", instance="test_instance", channel="ibm_cloud")

            assert client.channel == Channel.IBM_CLOUD.value
            assert client.account.channel == Channel.IBM_CLOUD.value

    @patch("qiskit_serverless.core.clients.serverless_client.ServerlessClient._verify_credentials")
    @patch("qiskit_ibm_runtime.accounts.management._DEFAULT_ACCOUNT_CONFIG_JSON_FILE")
    def test_backward_compatibility_with_explicit_ibm_quantum_platform(self, mock_file_path, mock_verify):
        """Test backward compatibility when IBM_QUANTUM_PLATFORM is explicitly provided."""
        mock_verify.return_value = None

        with tempfile.NamedTemporaryFile() as temp_file:
            mock_file_path.return_value = temp_file.name

            # This is how users might have been calling it before
            client = IBMServerlessClient(token="test_token", instance="test_instance", channel="ibm_quantum_platform")

            assert client.channel == Channel.IBM_QUANTUM_PLATFORM.value
            assert client.account.channel == Channel.IBM_QUANTUM_PLATFORM.value


if __name__ == "__main__":
    unittest.main()
