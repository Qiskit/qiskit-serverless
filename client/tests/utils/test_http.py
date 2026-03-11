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
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer test-token"
        assert "Instance" not in headers
        assert "Channel" not in headers

    def test_with_token_and_instance(self):
        """Test headers with token and instance."""
        headers = get_headers(token="test-token", instance="test-instance")
        assert headers["Authorization"] == "Bearer test-token"
        assert headers["Service-CRN"] == "test-instance"
        assert "Service-Channel" not in headers

    def test_with_token_and_channel(self):
        """Test headers with token and channel."""
        headers = get_headers(token="test-token", channel="ibm_cloud")
        assert headers["Authorization"] == "Bearer test-token"
        assert headers["Service-Channel"] == "ibm_cloud"
        assert "Service-CRN" not in headers

    def test_with_all_parameters(self):
        """Test headers with all parameters."""
        headers = get_headers(token="test-token", instance="test-instance", channel="ibm_quantum_platform")
        assert headers["Authorization"] == "Bearer test-token"
        assert headers["Service-CRN"] == "test-instance"
        assert headers["Service-Channel"] == "ibm_quantum_platform"

    def test_with_empty_token(self):
        """Test headers with empty token."""
        headers = get_headers(token="")
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer "

    def test_with_none_instance(self):
        """Test headers with None instance (should not be included)."""
        headers = get_headers(token="test-token", instance=None)
        assert "Authorization" in headers
        assert "Service-CRN" not in headers

    def test_with_none_channel(self):
        """Test headers with None channel (should not be included)."""
        headers = get_headers(token="test-token", channel=None)
        assert "Authorization" in headers
        assert "Service-Channel" not in headers

    def test_with_empty_string_instance(self):
        """Test headers with empty string instance."""
        headers = get_headers(token="test-token", instance="")
        assert headers["Service-CRN"] == ""

    def test_with_empty_string_channel(self):
        """Test headers with empty string channel."""
        headers = get_headers(token="test-token", channel="")
        assert headers["Service-Channel"] == ""

    def test_bearer_prefix_format(self):
        """Test that Authorization header has correct Bearer prefix."""
        headers = get_headers(token="my-secret-token")
        assert headers["Authorization"].startswith("Bearer ")
        assert "my-secret-token" in headers["Authorization"]

    def test_headers_are_dict(self):
        """Test that returned headers are a dictionary."""
        headers = get_headers(token="test-token")
        assert isinstance(headers, dict)

    def test_with_special_characters_in_token(self):
        """Test headers with special characters in token."""
        special_token = "token-with_special.chars!@#"
        headers = get_headers(token=special_token)
        assert headers["Authorization"] == f"Bearer {special_token}"

    def test_with_long_token(self):
        """Test headers with very long token."""
        long_token = "a" * 1000
        headers = get_headers(token=long_token)
        assert headers["Authorization"] == f"Bearer {long_token}"

    def test_with_crn_instance(self):
        """Test headers with CRN format instance."""
        crn = "crn:v1:bluemix:public:quantum-computing:us-east:a/abc123:::"
        headers = get_headers(token="test-token", instance=crn)
        assert headers["Service-CRN"] == crn

    def test_channel_values(self):
        """Test headers with different channel values."""
        for channel in ["ibm_cloud", "ibm_quantum_platform", "local"]:
            headers = get_headers(token="test-token", channel=channel)
            assert headers["Service-Channel"] == channel

    def test_headers_immutability(self):
        """Test that modifying returned headers doesn't affect subsequent calls."""
        headers1 = get_headers(token="token1")
        headers1["Custom"] = "value"

        headers2 = get_headers(token="token2")
        assert "Custom" not in headers2


if __name__ == "__main__":
    unittest.main()
