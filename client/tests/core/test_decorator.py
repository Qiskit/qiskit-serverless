"""Test decorators."""

from unittest import TestCase

from quantum_serverless import QuantumServerless, get
from quantum_serverless.core.decorators import run_qiskit_remote


class TestDecorators(TestCase):
    """Test decorators."""

    def test_run_qiskit_remote(self):
        """Test for run_qiskit_remote."""

        serverless = QuantumServerless()

        @run_qiskit_remote(target={"cpu": 1})
        def ultimate_function(ultimate_argument: int):
            """Test function."""
            print("Printing function argument:", ultimate_argument)
            return 42

        with serverless.context():
            reference = ultimate_function(1)

            result = get(reference)

            self.assertEqual(result, 42)
