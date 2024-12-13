# This code is part of Qiskit.
#
# (C) Copyright IBM 2023.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""QiskitPattern serializers tests."""
import json
from unittest import TestCase, skip

import numpy as np
from qiskit.circuit.random import random_circuit
from qiskit_ibm_runtime import QiskitRuntimeService

from qiskit_serverless.core.constants import JOB_ARGUMENTS_FILE
from qiskit_serverless.serializers.program_serializers import (
    QiskitObjectsDecoder,
    QiskitObjectsEncoder,
    get_arguments,
)


class TestProgramSerializers(TestCase):
    """Tests for program serializers."""

    def test_circuit_serialization(self):
        """Tests circuit serialization."""
        circuit = random_circuit(4, 2)
        encoded_arguments = json.dumps({"circuit": circuit}, cls=QiskitObjectsEncoder)
        decoded_arguments = json.loads(encoded_arguments, cls=QiskitObjectsDecoder)
        self.assertEqual(circuit, decoded_arguments.get("circuit"))

    def test_ndarray_serialization(self):
        """Tests ndarray serialization."""
        array = np.array([[42.0], [0.0]])
        encoded_arguments = json.dumps({"array": array}, cls=QiskitObjectsEncoder)
        decoded_arguments = json.loads(encoded_arguments, cls=QiskitObjectsDecoder)
        self.assertTrue(all(np.equal(array, decoded_arguments.get("array"))))

    @skip("External service call.")
    def test_runtime_service_serialization(self):
        """Tests runtime service serialization."""
        service = QiskitRuntimeService()
        encoded_arguments = json.dumps({"service": service}, cls=QiskitObjectsEncoder)
        decoded_arguments = json.loads(encoded_arguments, cls=QiskitObjectsDecoder)
        self.assertIsInstance(decoded_arguments.get("service"), QiskitRuntimeService)


class TestArgParsing(TestCase):
    """Tests argument parsing,"""

    def test_argument_parsing(self):
        """Tests argument parsing."""
        circuit = random_circuit(4, 2)
        array = np.array([[42.0], [0.0]])

        with open(JOB_ARGUMENTS_FILE, "w", encoding="utf-8") as f:
            json.dump({"circuit": circuit, "array": array}, f, cls=QiskitObjectsEncoder)

        parsed_arguments = get_arguments()
        self.assertEqual(list(parsed_arguments.keys()), ["circuit", "array"])
