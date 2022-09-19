"""Tests for parallel transpiler."""
from unittest import TestCase

from qiskit import QuantumCircuit
from qiskit.circuit.random import random_circuit
from qiskit.providers.fake_provider import FakeAlmadenV2, FakeBrooklynV2

from quantum_serverless import QuantumServerless
from quantum_serverless.exception import QuantumServerlessException
from quantum_serverless.library import parallel_transpile


class TestParallelTranspile(TestCase):
    """TestParallelTranspile."""

    def test_transpile(self):
        """Tests transpile."""

        circuit1 = random_circuit(5, 3)
        circuit2 = random_circuit(5, 3)

        backend1 = FakeAlmadenV2()
        backend2 = FakeBrooklynV2()

        with QuantumServerless().context():
            transpiled_circuits = parallel_transpile(
                circuits=[circuit1, [circuit1, circuit2]], backends=[backend1, backend2]
            )
            self.assertIsInstance(transpiled_circuits[0], QuantumCircuit)
            self.assertIsInstance(transpiled_circuits[1], list)
            self.assertEqual(len(transpiled_circuits[1]), 2)
            for tcirc in transpiled_circuits[1]:
                self.assertIsInstance(tcirc, QuantumCircuit)

    def test_transpile_fail(self):
        """Test failing cases for parallel transpile."""
        circuit1 = random_circuit(5, 3)

        backend1 = FakeAlmadenV2()
        backend2 = FakeBrooklynV2()

        with QuantumServerless().context():
            # inconsistent number of circuits and backends
            with self.assertRaises(QuantumServerlessException):
                parallel_transpile(circuits=[circuit1], backends=[backend1, backend2])
