"""Parallel transpiler."""
from typing import List, Union

import ray
from qiskit import QuantumCircuit, transpile
from qiskit.providers import Backend

from quantum_serverless.exception import QuantumServerlessException
from quantum_serverless import remote

transpile_ray = remote(transpile)


@remote
def remote_transpile(
    circuits: List[Union[QuantumCircuit, List[QuantumCircuit]]], backends: List[Backend]
) -> List[List[QuantumCircuit]]:
    """Remote transpile."""
    transpile_circuits_tasks = [
        transpile_ray.remote(circuits=circuits, backend=backend)
        for circuits, backend in zip(circuits, backends)
    ]
    return ray.get(transpile_circuits_tasks)


def parallel_transpile(
    circuits: List[Union[QuantumCircuit, List[QuantumCircuit]]], backends: List[Backend]
):
    """Transpile circuits in parallel using core of local machine or remote raylets.

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
    circuits_id = ray.put(circuits)
    backends_id = ray.put(backends)
    return ray.get(remote_transpile.remote(circuits_id, backends_id))
