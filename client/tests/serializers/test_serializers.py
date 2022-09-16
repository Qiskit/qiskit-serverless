"""Serializers tests."""

from unittest import TestCase

import ray
from qiskit import QuantumCircuit
from qiskit.circuit.random import random_circuit

from quantum_serverless import QuantumServerless
from quantum_serverless.serializers.serializers import (
    circuit_serializer,
    circuit_deserializer,
)


@ray.remote
def test_circuit_function(circuit: QuantumCircuit):
    """Test function."""
    return circuit.name


class TestSerializers(TestCase):
    """TestSerializers."""

    def test_quantum_circuit_serializers(self):
        """Tests quantum service serialization."""
        serverless = QuantumServerless()
        with serverless.context():
            ray.util.register_serializer(
                QuantumCircuit,
                serializer=circuit_serializer,
                deserializer=circuit_deserializer,
            )

            res = ray.get(test_circuit_function.remote(random_circuit(3, 2)))
            self.assertTrue("circuit" in res)
