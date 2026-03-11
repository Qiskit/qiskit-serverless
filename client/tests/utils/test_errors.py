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

"""Tests for error utilities."""

import json
import unittest

from qiskit_serverless.utils.errors import (
    is_http_standard_error,
    ErrorCodes,
    format_err_msg,
)


class TestIsHttpStandardError(unittest.TestCase):
    """Tests for is_http_standard_error function."""

    def test_valid_http_error_codes(self):
        """Test that valid HTTP error codes are recognized."""
        # Common HTTP error codes
        assert is_http_standard_error(400)  # Bad Request
        assert is_http_standard_error(401)  # Unauthorized
        assert is_http_standard_error(403)  # Forbidden
        assert is_http_standard_error(404)  # Not Found
        assert is_http_standard_error(500)  # Internal Server Error
        assert is_http_standard_error(502)  # Bad Gateway
        assert is_http_standard_error(503)  # Service Unavailable

    def test_boundary_http_codes(self):
        """Test boundary values for HTTP error codes."""
        assert is_http_standard_error(100)  # Minimum valid
        assert is_http_standard_error(599)  # Maximum valid
        assert not is_http_standard_error(99)  # Below minimum
        assert not is_http_standard_error(600)  # Above maximum

    def test_non_http_codes(self):
        """Test that non-HTTP codes return False."""
        assert not is_http_standard_error(0)
        assert not is_http_standard_error(-1)
        assert not is_http_standard_error(1000)

    def test_string_codes(self):
        """Test that string codes return False."""
        assert not is_http_standard_error("400")
        assert not is_http_standard_error("AUTH1001")
        assert not is_http_standard_error("")


class TestErrorCodes(unittest.TestCase):
    """Tests for ErrorCodes class."""

    def test_error_codes_exist(self):
        """Test that expected error codes are defined."""
        assert ErrorCodes.AUTH1001 == "AUTH1001"
        assert ErrorCodes.JSON1001 == "JSON1001"
        assert ErrorCodes.HTTP_STD_ERROR == "HTTP_STD_ERROR"


class TestFormatErrMsg(unittest.TestCase):
    """Tests for format_err_msg function."""

    def test_format_with_known_error_code(self):
        """Test formatting with a known error code."""
        result = format_err_msg(ErrorCodes.AUTH1001)
        assert "Message:" in result
        assert "Code:" in result
        assert "AUTH1001" in result
        assert "Connection error" in result

    def test_format_with_http_error_code(self):
        """Test formatting with HTTP error code."""
        result = format_err_msg(404)
        assert "Message:" in result
        assert "Code:" in result
        assert "404" in result
        assert "Http bad request" in result

    def test_format_with_unknown_error_code(self):
        """Test formatting with unknown error code."""
        result = format_err_msg("UNKNOWN_CODE")
        assert "Message:" in result
        assert "Something went wrong" in result
        assert "UNKNOWN_CODE" in result

    def test_format_with_details_as_string(self):
        """Test formatting with details as plain string."""
        result = format_err_msg(ErrorCodes.AUTH1001, details="Connection timeout")
        assert "Details:" in result
        assert "Connection timeout" in result

    def test_format_with_details_as_json_dict(self):
        """Test formatting with details as JSON dictionary."""
        details_dict = {"field": ["error message"], "another_field": "single error"}
        details_json = json.dumps(details_dict)
        result = format_err_msg(ErrorCodes.JSON1001, details=details_json)
        assert "Details:" in result
        assert "field: error message" in result
        assert "another_field: single error" in result

    def test_format_with_details_as_json_list(self):
        """Test formatting with details as JSON with list values."""
        details_dict = {"errors": ["error1", "error2", "error3"]}
        details_json = json.dumps(details_dict)
        result = format_err_msg(ErrorCodes.AUTH1001, details=details_json)
        assert "Details:" in result
        assert "errors: error1" in result  # Should take first item

    def test_format_with_empty_details(self):
        """Test formatting with empty details."""
        result = format_err_msg(ErrorCodes.AUTH1001, details="")
        assert "Message:" in result
        assert "Code:" in result
        # Empty details should not add Details section
        assert "Details:" not in result

    def test_format_with_invalid_json_details(self):
        """Test formatting with invalid JSON in details."""
        result = format_err_msg(ErrorCodes.JSON1001, details="not valid json {")
        assert "Details:" in result
        assert "not valid json" in result

    def test_format_with_zero_code(self):
        """Test formatting with zero error code."""
        result = format_err_msg(0)
        assert "Message:" in result
        assert "Something went wrong" in result

    def test_format_with_empty_dict_values(self):
        """Test formatting with empty dictionary values in details."""
        details_dict = {"field1": [], "field2": ""}
        details_json = json.dumps(details_dict)
        result = format_err_msg(ErrorCodes.AUTH1001, details=details_json)
        # Empty values should not be included
        assert "field1:" not in result
        assert "field2:" not in result

    def test_format_multiline_output(self):
        """Test that output contains proper line breaks."""
        result = format_err_msg(ErrorCodes.AUTH1001, details="test details")
        lines = result.split("\n")
        assert len(lines) > 1
        assert any("Message:" in line for line in lines)
        assert any("Code:" in line for line in lines)
        assert any("Details:" in line for line in lines)


if __name__ == "__main__":
    unittest.main()
