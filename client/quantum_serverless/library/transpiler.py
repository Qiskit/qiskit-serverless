"""Parallel transpiler."""
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
