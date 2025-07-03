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
from qiskit_serverless.exception import QiskitServerlessException


class TestIBMServerlessClient(unittest.TestCase):
    """Unit tests for IBMServerlessClient."""

    @patch(
        "qiskit_serverless.core.clients.serverless_client.ServerlessClient._verify_credentials"
    )
    @patch("qiskit_ibm_runtime.accounts.management._DEFAULT_ACCOUNT_CONFIG_JSON_FILE")
    def test_save_load_account(self, mock_file_path, mock_verify_credentials):
        """Test saving and loading accounts with the IBMServerlessClient."""

        # Mock ServerlessClient credential verification
        mock_verify_credentials.return_value = None

        # Save config in a temporary file
        with tempfile.NamedTemporaryFile() as temp_file:
            mock_file_path.return_value = temp_file.name

        channels_to_test = [
            Channel.IBM_QUANTUM.value,
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
                self.assertEqual(client.account.channel, use_channel)
                self.assertEqual(client.account.token, use_token)
                self.assertEqual(client.account.instance, use_instance)

    @patch("qiskit_ibm_runtime.accounts.management._DEFAULT_ACCOUNT_CONFIG_JSON_FILE")
    def test_save_wrong_instance(self, mock_file_path):
        """Test saving with wrong instance format (ibm_quantum channel)."""

        # Save config in a temporary file
        with tempfile.NamedTemporaryFile() as temp_file:
            mock_file_path.return_value = temp_file.name

        use_channel = Channel.IBM_QUANTUM.value
        use_instance = "wrong_ibm_quantum_instance"
        use_token = "save_token"
        use_name = f"test_save_account_{uuid.uuid4().hex}"

        with self.assertRaisesRegex(
            QiskitServerlessException,
            r"Invalid format in account inputs - 'Invalid `instance` value\. "
            "Expected hub/group/project format, got wrong_ibm_quantum_instance'",
        ):

            IBMServerlessClient.save_account(
                token=use_token,
                name=use_name,
                instance=use_instance,
                channel=use_channel,
            )

    def test_init_wrong_instance(self):
        """Test initializing account with wrong instance format (ibm_quantum channel)."""

        use_channel = Channel.IBM_QUANTUM.value
        use_instance = "wrong_ibm_quantum_instance"
        use_token = "save_token"

        with self.assertRaisesRegex(
            QiskitServerlessException,
            r"Invalid format in account inputs - 'Invalid `instance` value\. "
            "Expected hub/group/project format, got wrong_ibm_quantum_instance'",
        ):

            IBMServerlessClient(
                channel=use_channel, instance=use_instance, token=use_token
            )


if __name__ == "__main__":
    unittest.main()
