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
from typing import Dict, Any, List
from unittest import TestCase

from qiskit import QuantumCircuit
from qiskit.circuit.random import random_circuit

from quantum_serverless import QuantumServerless, get
from quantum_serverless.core.decorators import (
    run_qiskit_remote,
    distribute_task,
    Target,
    fetch_execution_meta,
)
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

        @run_qiskit_remote()
        def another_function(
            circuit: List[QuantumCircuit], other_circuit: QuantumCircuit
        ):
            """Another test function."""
            return circuit[0].compose(other_circuit, range(5)).depth()

        @run_qiskit_remote(target={"cpu": 1})
        def ultimate_function(ultimate_argument: int):
            """Test function."""
            print("Printing function argument:", ultimate_argument)
            mid_result = get(
                another_function(
                    [random_circuit(5, 2)], other_circuit=random_circuit(5, 2)
                )
            )
            return mid_result

        with self.assertWarns(Warning), serverless.context():
            reference = ultimate_function(1)
            result = get(reference)
            self.assertEqual(result, 4)

    def test_distribute_task(self):
        """Test for run_qiskit_remote."""

        serverless = QuantumServerless()

        @distribute_task()
        def another_function(
            circuit: List[QuantumCircuit], other_circuit: QuantumCircuit
        ):
            """Another test function."""
            return circuit[0].compose(other_circuit, range(5)).depth()

        @distribute_task(target={"cpu": 1})
        def ultimate_function(ultimate_argument: int):
            """Test function."""
            print("Printing function argument:", ultimate_argument)
            mid_result = get(
                another_function(
                    [random_circuit(5, 2)], other_circuit=random_circuit(5, 2)
                )
            )
            return mid_result

        with serverless.context():
            reference = ultimate_function(1)
            result = get(reference)
            self.assertEqual(result, 4)

    def test_target(self):
        """Test for target."""
        target_expected = Target(pip=["requests", "qiskit==0.39.2"])
        target = Target.from_dict({"pip": ["requests", "qiskit==0.39.2"]})
        self.assertEqual(target.pip, target_expected.pip)

    def test_remote_with_state_injection(self):
        """Tests remote with state injection."""
        serverless = QuantumServerless()
        state_handler = TestHandler()

        @distribute_task(target={"cpu": 1}, state=state_handler)
        def ultimate_function_with_state(state: StateHandler, ultimate_argument: int):
            """Test function."""
            state.set("some_key", {"result": ultimate_argument})
            return state.get("some_key")

        with serverless.context():
            reference = (
                ultimate_function_with_state(  # pylint: disable=no-value-for-parameter
                    1
                )
            )

            result = get(reference)

            self.assertEqual(result, {"result": 1})

    def test_execution_meta(self):
        """Tests execution meta fetching."""
        args = ([random_circuit(5, 2)], 42, random_circuit(3, 1))
        kwargs = {
            "some_kwarg": random_circuit(3, 1),
            "some_kwargs": [random_circuit(3, 1)],
        }
        meta = fetch_execution_meta(*args, **kwargs)

        expecting = {
            "qs.args.arg_0.0": [5, 2],
            "qs.args.arg_2": [3, 1],
            "qs.kwargs.some_kwarg": [3, 1],
            "qs.kwargs.some_kwargs.0": [3, 1],
        }
        self.assertEqual(expecting, meta)
