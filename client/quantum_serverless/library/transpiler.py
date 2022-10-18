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

"""
=================================================
Transpiler (:mod:`quantum_serverless.transpiler`)
=================================================

.. currentmodule:: quantum_serverless.library.transpiler

Quantum serverless transpiler functions
=======================================

.. autosummary::
    :toctree: ../stubs/

    parallel_transpile
"""
from typing import List, Union

from qiskit import QuantumCircuit, transpile
from qiskit.providers import Backend

from quantum_serverless.exception import QuantumServerlessException
from quantum_serverless import run_qiskit_remote, get, put

transpile_ray = run_qiskit_remote()(transpile)


@run_qiskit_remote()
def remote_transpile(
    circuits: List[Union[QuantumCircuit, List[QuantumCircuit]]], backends: List[Backend]
) -> List[List[QuantumCircuit]]:
    """Remote transpile."""
    transpile_circuits_tasks = [
        transpile_ray(circuits=circuits, backend=backend)
        for circuits, backend in zip(circuits, backends)
    ]
    return get(transpile_circuits_tasks)


def parallel_transpile(
    circuits: List[Union[QuantumCircuit, List[QuantumCircuit]]], backends: List[Backend]
):
    """Transpile circuits in parallel using core of local machine or remote raylets.

    Example:
        >>> parallel_transpile([circuit1, [circuit2, circuit3]], [backend1, backend2])
        >>> # [<QuantumCircuit ...>, [<QuantumCircuit ...>, <QuantumCircuit ...>]]

    Args:
        circuits: list of lists of circuits to transpile
        backends: list of backends to transpile circuits against

    Returns:
        list of transpiled circuits
    """
    if len(circuits) != len(backends):
        raise QuantumServerlessException(
            "Length of circuits must be equal to length of backends."
        )
    circuits_id = put(circuits)
    backends_id = put(backends)
    return get(remote_transpile(circuits_id, backends_id))
