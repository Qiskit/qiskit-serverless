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
