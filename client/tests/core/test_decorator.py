# This code is a Qiskit project.
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
from typing import Dict, Any
from unittest import TestCase

from quantum_serverless import QuantumServerless, get
from quantum_serverless.core.decorators import run_qiskit_remote, Target
from quantum_serverless.core.state import StateHandler


class TestHandler(StateHandler):
    """TestHandler"""

    def __init__(self):
        self.memory: Dict[str, Any] = {}

    def set(self, key: str, value: Dict[str, Any]):
        self.memory[key] = value

    def get(self, key: str):
        return self.memory.get(key)


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

        with serverless:
            reference = ultimate_function(1)

            result = get(reference)

            self.assertEqual(result, 42)

    def test_target(self):
        """Test for target."""
        target_expected = Target(pip=["requests", "qiskit==0.39.2"])
        target = Target.from_dict({"pip": ["requests", "qiskit==0.39.2"]})
        self.assertEqual(target.pip, target_expected.pip)

    def test_remote_with_state_injection(self):
        """Tests remote with state injection."""
        serverless = QuantumServerless()
        state_handler = TestHandler()

        @run_qiskit_remote(target={"cpu": 1}, state=state_handler)
        def ultimate_function_with_state(state: StateHandler, ultimate_argument: int):
            """Test function."""
            state.set("some_key", {"result": ultimate_argument})
            return state.get("some_key")

        with serverless:
            reference = (
                ultimate_function_with_state(  # pylint: disable=no-value-for-parameter
                    1
                )
            )

            result = get(reference)

            self.assertEqual(result, {"result": 1})
