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
import os
from unittest import TestCase, skip
from unittest.mock import patch
from uuid import uuid4

import shutil
import tempfile
import numpy as np
from qiskit.circuit.random import random_circuit
from qiskit_ibm_runtime import QiskitRuntimeService

from qiskit_serverless.core.constants import DATA_PATH, ENV_JOB_ID_GATEWAY
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

    def setUp(self):
        self.test_data_dir = tempfile.mkdtemp()
        self.arguments_dir = os.path.join(self.test_data_dir, "arguments")
        os.makedirs(self.arguments_dir, exist_ok=True)

        self.original_data_path = os.environ.get(DATA_PATH)
        os.environ[DATA_PATH] = self.test_data_dir

    def tearDown(self):
        if self.original_data_path is not None:
            os.environ[DATA_PATH] = self.original_data_path
        elif DATA_PATH in os.environ:
            del os.environ[DATA_PATH]

        shutil.rmtree(self.test_data_dir)

    @patch.dict(os.environ, {ENV_JOB_ID_GATEWAY: str(uuid4())})
    def test_argument_parsing(self):
        """Tests argument parsing."""
        circuit = random_circuit(4, 2)
        array = np.array([[42.0], [0.0]])

        job_id_gateway = os.environ.get(ENV_JOB_ID_GATEWAY)
        arguments_file_path = f"{self.test_data_dir}/arguments/{job_id_gateway}.json"

        with open(arguments_file_path, "w", encoding="utf-8") as f:
            json.dump({"circuit": circuit, "array": array}, f, cls=QiskitObjectsEncoder)

        parsed_arguments = get_arguments()
        self.assertEqual(list(parsed_arguments.keys()), ["circuit", "array"])
