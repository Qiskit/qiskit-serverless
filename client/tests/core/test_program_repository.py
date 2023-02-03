"""Test program repository."""

from unittest import TestCase

from quantum_serverless.core.program import ProgramRepository


MOCK_URL = ""


def mocked_get_programs(*args, **kwargs):
    class MockResponse:
        def __init__(self, json_data, status_code):
            self.json_data = json_data
            self.status_code = status_code

        def json(self):
            return self.json_data

    if args[0] == 'http://someurl.com/test.json':
        return MockResponse({"key1": "value1"}, 200)
    elif args[0] == 'http://someotherurl.com/anothertest.json':
        return MockResponse({"key2": "value2"}, 200)

    return MockResponse(None, 404)


class TestRepository(TestCase):
    """Tests for program."""

    def test_repository_get_programs(self):
        """Tests program repository."""

        repository = ProgramRepository(
            host="localhost",
            port=8000
        )
        print(repository.get_programs())