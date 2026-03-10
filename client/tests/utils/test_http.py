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

"""Tests for HTTP utilities."""

import unittest

from qiskit_serverless.utils.http import get_headers


class TestGetHeaders(unittest.TestCase):
    """Tests for get_headers function."""

    def test_with_token_only(self):
        """Test headers with token only."""
        headers = get_headers(token="test-token")
        self.assertIn("Authorization", headers)
        self.assertEqual(headers["Authorization"], "Bearer test-token")
        self.assertNotIn("Instance", headers)
        self.assertNotIn("Channel", headers)

    def test_with_token_and_instance(self):
        """Test headers with token and instance."""
        headers = get_headers(token="test-token", instance="test-instance")
        self.assertEqual(headers["Authorization"], "Bearer test-token")
        self.assertEqual(headers["Service-CRN"], "test-instance")
        self.assertNotIn("Service-Channel", headers)

    def test_with_token_and_channel(self):
        """Test headers with token and channel."""
        headers = get_headers(token="test-token", channel="ibm_cloud")
        self.assertEqual(headers["Authorization"], "Bearer test-token")
        self.assertEqual(headers["Service-Channel"], "ibm_cloud")
        self.assertNotIn("Service-CRN", headers)

    def test_with_all_parameters(self):
        """Test headers with all parameters."""
        headers = get_headers(token="test-token", instance="test-instance", channel="ibm_quantum_platform")
        self.assertEqual(headers["Authorization"], "Bearer test-token")
        self.assertEqual(headers["Service-CRN"], "test-instance")
        self.assertEqual(headers["Service-Channel"], "ibm_quantum_platform")

    def test_with_empty_token(self):
        """Test headers with empty token."""
        headers = get_headers(token="")
        self.assertIn("Authorization", headers)
        self.assertEqual(headers["Authorization"], "Bearer ")

    def test_with_none_instance(self):
        """Test headers with None instance (should not be included)."""
        headers = get_headers(token="test-token", instance=None)
        self.assertIn("Authorization", headers)
        self.assertNotIn("Service-CRN", headers)

    def test_with_none_channel(self):
        """Test headers with None channel (should not be included)."""
        headers = get_headers(token="test-token", channel=None)
        self.assertIn("Authorization", headers)
        self.assertNotIn("Service-Channel", headers)

    def test_with_empty_string_instance(self):
        """Test headers with empty string instance."""
        headers = get_headers(token="test-token", instance="")
        self.assertEqual(headers["Service-CRN"], "")

    def test_with_empty_string_channel(self):
        """Test headers with empty string channel."""
        headers = get_headers(token="test-token", channel="")
        self.assertEqual(headers["Service-Channel"], "")

    def test_bearer_prefix_format(self):
        """Test that Authorization header has correct Bearer prefix."""
        headers = get_headers(token="my-secret-token")
        self.assertTrue(headers["Authorization"].startswith("Bearer "))
        self.assertIn("my-secret-token", headers["Authorization"])

    def test_headers_are_dict(self):
        """Test that returned headers are a dictionary."""
        headers = get_headers(token="test-token")
        self.assertIsInstance(headers, dict)

    def test_with_special_characters_in_token(self):
        """Test headers with special characters in token."""
        special_token = "token-with_special.chars!@#"
        headers = get_headers(token=special_token)
        self.assertEqual(headers["Authorization"], f"Bearer {special_token}")

    def test_with_long_token(self):
        """Test headers with very long token."""
        long_token = "a" * 1000
        headers = get_headers(token=long_token)
        self.assertEqual(headers["Authorization"], f"Bearer {long_token}")

    def test_with_crn_instance(self):
        """Test headers with CRN format instance."""
        crn = "crn:v1:bluemix:public:quantum-computing:us-east:a/abc123:::"
        headers = get_headers(token="test-token", instance=crn)
        self.assertEqual(headers["Service-CRN"], crn)

    def test_with_hub_group_project_instance(self):
        """Test headers with hub/group/project format instance."""
        hgp = "ibm-q/open/main"
        headers = get_headers(token="test-token", instance=hgp)
        self.assertEqual(headers["Service-CRN"], hgp)

    def test_channel_values(self):
        """Test headers with different channel values."""
        for channel in ["ibm_cloud", "ibm_quantum_platform", "local"]:
            headers = get_headers(token="test-token", channel=channel)
            self.assertEqual(headers["Service-Channel"], channel)

    def test_headers_immutability(self):
        """Test that modifying returned headers doesn't affect subsequent calls."""
        headers1 = get_headers(token="token1")
        headers1["Custom"] = "value"

        headers2 = get_headers(token="token2")
        self.assertNotIn("Custom", headers2)


if __name__ == "__main__":
    unittest.main()
