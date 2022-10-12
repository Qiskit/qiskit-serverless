# This code is part of Qiskit.
#
# (C) Copyright IBM 2022.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

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
