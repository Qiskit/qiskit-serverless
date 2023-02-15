"""Test program repository."""
import os.path
from unittest import TestCase

from quantum_serverless.core.program import ProgramRepository


class TestRepository(TestCase):
    """Tests for program."""

    def test_repository_get_programs(self):
        """Tests program repository."""

        repository = ProgramRepository(host="http://127.0.0.1", port=8000)
        print(repository.get_programs())

    def test_repository_get_program(self):
        """Tests single program fetch."""
        repository = ProgramRepository(
            host="http://127.0.0.1",
            port=8000,
            root=os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "..", "resources"
            ),
        )
        program = repository.get_program("hello_program")
        print(program)
