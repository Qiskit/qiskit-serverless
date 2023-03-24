"""Test nested_program repository."""
import json
import os.path
import shutil
from pathlib import Path
from unittest import TestCase, mock

from quantum_serverless.core.nested_program import NestedProgramRepository, NestedProgram

responses = {
    "http://localhost:80/v1/api/nested-programs/": {
        "count": 2,
        "results": [
            {
                "id": "be7e5406-d111-4768-9a93-7cedf4d46608",
                "created": "2023-02-15T14:38:41.120934Z",
                "updated": "2023-02-15T14:38:41.120975Z",
                "title": "hello_world",
                "description": "",
                "entrypoint": "hello_world.py",
                "working_dir": "./",
                "version": "0.0.0",
                "dependencies": None,
                "env_vars": None,
                "arguments": None,
                "tags": None,
                "public": None,
                "artifact": "urL_for_artifact",
            },
            {
                "id": "92d47ca1-adec-4407-b072-857265d0b02a",
                "created": "2023-02-15T16:05:12.791987Z",
                "updated": "2023-02-15T16:05:12.792044Z",
                "title": "Test",
                "description": "Test",
                "entrypoint": "test.py",
                "working_dir": "./",
                "version": "0.0.0",
                "dependencies": None,
                "env_vars": {"DEBUG": "1"},
                "arguments": None,
                "tags": None,
                "public": None,
                "artifact": "urL_for_artifact",
            },
        ],
    }
}


class MockResponse:
    """MockResponse."""

    def __init__(self, json_data):
        """General mock response.

        Args:
            json_data: data in response
        """
        self.json_data = json_data

    @property
    def text(self):
        """Text of response."""
        return json.dumps(self.json_data)

    @property
    def ok(self):  # pylint: disable=invalid-name
        """Status of response."""
        return True


class MockedStreamingResponse:
    """MockedStreamingResponse."""

    def __init__(self, file_path: str):
        self.file_path = file_path

    def iter_content(self):
        """Iterate through file content."""
        content = []
        with open(self.file_path, "rb") as file:
            content.append(file.read())
        return content

    @property
    def ok(self):  # pylint: disable=invalid-name
        """Status of response."""
        return True


def mocked_requests_get(**kwargs):
    """Mock request side effect."""
    url = kwargs.get("url")
    stream = kwargs.get("stream", False)
    result = None
    if not stream and url:
        result = MockResponse(responses.get(url, {}))
    if stream and url:
        result = MockedStreamingResponse(
            file_path=os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..",
                "resources",
                "nested_program.tar",
            )
        )
    return result


class TestRepository(TestCase):
    """Tests for repository."""

    def setUp(self) -> None:
        self.resources_folder = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "resources"
        )
        self.nested_programs_folder = os.path.join(self.resources_folder, "nested_programs")
        Path(self.nested_programs_folder).mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if os.path.exists(self.nested_programs_folder):
            shutil.rmtree(self.nested_programs_folder)

    @mock.patch("requests.get", side_effect=mocked_requests_get)
    def test_repository_get_nested_programs(self, mock_get):
        """Tests nested_program repository."""

        repository = NestedProgramRepository(host="http://localhost")
        nested_programs = repository.get_nested_programs()
        self.assertEqual(nested_programs, ["hello_world", "Test"])
        self.assertEqual(len(mock_get.call_args_list), 1)

    @mock.patch("requests.get", side_effect=mocked_requests_get)
    def test_repository_get_nested_program(self, mock_get):
        """Tests single nested_program fetch."""
        repository = NestedProgramRepository(
            host="http://localhost", folder=self.nested_programs_folder
        )
        nested_program = repository.get_nested_program("hello_world")
        self.assertEqual(nested_program.title, "hello_world")
        self.assertEqual(nested_program.version, "0.0.0")
        self.assertIsInstance(nested_program, NestedProgram)
        self.assertEqual(len(mock_get.call_args_list), 2)
