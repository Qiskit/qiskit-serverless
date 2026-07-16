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

from typing import List

import pytest

from qiskit import QuantumCircuit
from qiskit.circuit.random import random_circuit

import ray
from qiskit_serverless import get
from qiskit_serverless.core.decorators import (
    distribute_task,
    get_refs_by_status,
    put,
    Target,
    fetch_execution_meta,
)


class TestDecorators:
    """Test decorators."""

    def test_distribute_task(self):
        """Test for run_qiskit_remote."""

        @distribute_task()
        def another_function(circuit: List[QuantumCircuit], other_circuit: QuantumCircuit):
            """Another test function."""
            return circuit[0].compose(other_circuit, range(5)).depth()

        @distribute_task(target={"cpu": 1})
        def ultimate_function(ultimate_argument: int):
            """Test function."""
            print("Printing function argument:", ultimate_argument)
            mid_result = get(another_function([random_circuit(5, 2)], other_circuit=random_circuit(5, 2)))
            return mid_result

        with ray.init():
            reference = ultimate_function(1)
            result = get(reference)
            assert result == 4

    def test_distribute_task_deprecation_warning(self):
        """`distribute_task` should raise a DeprecationWarning pointing to ray.remote."""
        with pytest.warns(DeprecationWarning, match="ray.remote"):

            @distribute_task()
            def _some_function():
                return 42

    def test_get_deprecation_warning(self):
        """`get` should raise a DeprecationWarning pointing to ray.get."""
        with ray.init():
            reference = ray.put(42)
            with pytest.warns(DeprecationWarning, match="ray.get"):
                assert get(reference) == 42

    def test_put_deprecation_warning(self):
        """`put` should raise a DeprecationWarning pointing to ray.put."""
        with ray.init():
            with pytest.warns(DeprecationWarning, match="ray.put"):
                put(42)

    def test_get_refs_by_status_deprecation_warning(self):
        """`get_refs_by_status` should raise a DeprecationWarning pointing to ray.wait."""
        with ray.init():
            reference = ray.put(42)
            with pytest.warns(DeprecationWarning, match="ray.wait"):
                get_refs_by_status([reference])

    def test_target(self):
        """Test for target."""
        target_expected = Target(pip=["requests", "qiskit==0.39.2"])
        target = Target.from_dict({"pip": ["requests", "qiskit==0.39.2"]})
        assert target.pip == target_expected.pip

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
        assert expecting == meta
