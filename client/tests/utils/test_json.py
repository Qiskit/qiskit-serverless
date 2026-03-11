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

"""Tests for JSON utilities."""

import json
import unittest
from unittest.mock import Mock
from json import JSONEncoder

import pytest
import requests

from qiskit_serverless.utils.json import (
    JsonSerializable,
    is_jsonable,
    safe_json_request_as_list,
    safe_json_request_as_dict,
    safe_json_request,
)
from qiskit_serverless.exception import QiskitServerlessException


class ConcreteJsonSerializable(JsonSerializable):
    """Concrete implementation of JsonSerializable for testing."""

    def __init__(self, data):
        self.data = data

    def to_dict(self) -> dict:
        return {"data": self.data}

    @classmethod
    def from_dict(cls, dictionary: dict):
        return cls(dictionary.get("data"))


class TestJsonSerializable(unittest.TestCase):
    """Tests for JsonSerializable abstract class."""

    def test_to_dict(self):
        """Test to_dict method."""
        obj = ConcreteJsonSerializable("test_value")
        result = obj.to_dict()
        assert result == {"data": "test_value"}

    def test_from_dict(self):
        """Test from_dict class method."""
        obj = ConcreteJsonSerializable.from_dict({"data": "test_value"})
        assert obj.data == "test_value"

    def test_round_trip(self):
        """Test serialization and deserialization round trip."""
        original = ConcreteJsonSerializable("test_data")
        dict_form = original.to_dict()
        restored = ConcreteJsonSerializable.from_dict(dict_form)
        assert original.data == restored.data


class TestIsJsonable(unittest.TestCase):
    """Tests for is_jsonable function."""

    def test_with_simple_types(self):
        """Test with simple JSON-serializable types."""
        assert is_jsonable("string")
        assert is_jsonable(123)
        assert is_jsonable(45.67)
        assert is_jsonable(True)
        assert is_jsonable(False)
        assert is_jsonable(None)

    def test_with_collections(self):
        """Test with JSON-serializable collections."""
        assert is_jsonable([1, 2, 3])
        assert is_jsonable({"key": "value"})
        assert is_jsonable({"nested": {"key": "value"}})
        assert is_jsonable([{"key": "value"}])

    def test_with_non_serializable_types(self):
        """Test with non-JSON-serializable types."""
        assert not is_jsonable(object())
        assert not is_jsonable(lambda x: x)
        assert not is_jsonable(set([1, 2, 3]))

    def test_with_custom_encoder(self):
        """Test with custom JSON encoder."""

        class CustomObject:  # pylint: disable=too-few-public-methods
            """Custom object for testing JSON encoding."""

        class CustomEncoder(JSONEncoder):
            """Custom JSON encoder for testing."""

            def default(self, o):
                if isinstance(o, CustomObject):
                    return "custom"
                return super().default(o)

        obj = CustomObject()
        assert not is_jsonable(obj)  # Without custom encoder
        assert is_jsonable(obj, cls=CustomEncoder)  # With custom encoder

    def test_with_empty_collections(self):
        """Test with empty collections."""
        assert is_jsonable([])
        assert is_jsonable({})
        assert is_jsonable("")


class TestSafeJsonRequestAsList(unittest.TestCase):
    """Tests for safe_json_request_as_list function."""

    def test_successful_list_response(self):
        """Test with successful response containing a list."""
        mock_response = Mock(spec=requests.Response)
        mock_response.ok = True
        mock_response.json.return_value = [{"id": 1}, {"id": 2}]
        mock_response.text = json.dumps([{"id": 1}, {"id": 2}])

        result = safe_json_request_as_list(lambda: mock_response)
        assert result == [{"id": 1}, {"id": 2}]

    def test_empty_list_response(self):
        """Test with successful response containing empty list."""
        mock_response = Mock(spec=requests.Response)
        mock_response.ok = True
        mock_response.json.return_value = []
        mock_response.text = "[]"

        result = safe_json_request_as_list(lambda: mock_response)
        assert result == []

    def test_failed_response(self):
        """Test with failed response."""
        mock_response = Mock(spec=requests.Response)
        mock_response.ok = False
        mock_response.status_code = 404
        mock_response.text = "Not found"

        with pytest.raises(QiskitServerlessException):
            safe_json_request_as_list(lambda: mock_response)


class TestSafeJsonRequestAsDict(unittest.TestCase):
    """Tests for safe_json_request_as_dict function."""

    def test_successful_dict_response(self):
        """Test with successful response containing a dict."""
        mock_response = Mock(spec=requests.Response)
        mock_response.ok = True
        mock_response.json.return_value = {"key": "value", "count": 42}
        mock_response.text = json.dumps({"key": "value", "count": 42})

        result = safe_json_request_as_dict(lambda: mock_response)
        assert result == {"key": "value", "count": 42}

    def test_empty_dict_response(self):
        """Test with successful response containing empty dict."""
        mock_response = Mock(spec=requests.Response)
        mock_response.ok = True
        mock_response.json.return_value = {}
        mock_response.text = "{}"

        result = safe_json_request_as_dict(lambda: mock_response)
        assert result == {}

    def test_failed_response(self):
        """Test with failed response."""
        mock_response = Mock(spec=requests.Response)
        mock_response.ok = False
        mock_response.status_code = 500
        mock_response.text = "Internal server error"

        with pytest.raises(QiskitServerlessException):
            safe_json_request_as_dict(lambda: mock_response)


class TestSafeJsonRequest(unittest.TestCase):
    """Tests for safe_json_request function."""

    def test_successful_request(self):
        """Test with successful request."""
        mock_response = Mock(spec=requests.Response)
        mock_response.ok = True
        mock_response.json.return_value = {"status": "success"}
        mock_response.text = json.dumps({"status": "success"})

        result = safe_json_request(lambda: mock_response)
        assert result == {"status": "success"}

    def test_failed_request_with_error_code(self):
        """Test with failed request containing error code."""
        mock_response = Mock(spec=requests.Response)
        mock_response.ok = False
        mock_response.status_code = 401
        mock_response.text = json.dumps({"error": "Unauthorized"})

        with pytest.raises(QiskitServerlessException) as context:
            safe_json_request(lambda: mock_response)

        assert "401" in str(context.value)

    def test_failed_request_with_json_error(self):
        """Test with failed request and JSON decode error."""
        mock_response = Mock(spec=requests.Response)
        mock_response.ok = False
        mock_response.status_code = 400
        mock_response.text = "Not valid JSON"
        mock_response.json.side_effect = json.JSONDecodeError("msg", "doc", 0)

        with pytest.raises(QiskitServerlessException):
            safe_json_request(lambda: mock_response)

    def test_successful_request_with_non_dict_response(self):
        """Test with successful request returning non-dict."""
        mock_response = Mock(spec=requests.Response)
        mock_response.ok = True
        mock_response.json.return_value = [1, 2, 3]
        mock_response.text = "[1, 2, 3]"

        result = safe_json_request(lambda: mock_response)
        assert result == [1, 2, 3]

    def test_request_with_connection_error(self):
        """Test with connection error."""

        def failing_request():
            raise requests.ConnectionError("Connection failed")

        with pytest.raises(QiskitServerlessException):
            safe_json_request(failing_request)

    def test_request_with_timeout(self):
        """Test with timeout error."""

        def timeout_request():
            raise requests.Timeout("Request timed out")

        with pytest.raises(QiskitServerlessException):
            safe_json_request(timeout_request)

    def test_successful_request_with_nested_data(self):
        """Test with successful request containing nested data."""
        nested_data = {
            "results": [{"id": 1, "data": {"value": "a"}}, {"id": 2, "data": {"value": "b"}}],
            "metadata": {"count": 2},
        }
        mock_response = Mock(spec=requests.Response)
        mock_response.ok = True
        mock_response.json.return_value = nested_data
        mock_response.text = json.dumps(nested_data)

        result = safe_json_request(lambda: mock_response)
        assert result == nested_data

    def test_failed_request_with_detailed_error(self):
        """Test with failed request containing detailed error message."""
        error_details = {"error": "Validation failed", "details": {"field": "name", "message": "Required field"}}
        mock_response = Mock(spec=requests.Response)
        mock_response.ok = False
        mock_response.status_code = 422
        mock_response.text = json.dumps(error_details)
        mock_response.json.return_value = error_details

        with pytest.raises(QiskitServerlessException) as context:
            safe_json_request(lambda: mock_response)

        exception_str = str(context.value)
        assert "422" in exception_str


if __name__ == "__main__":
    unittest.main()
