# This code is a Qiskit project.
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


"""This is benchmark program for stress testing compute resources."""
import argparse
import time
from typing import List

from qiskit import QuantumCircuit, transpile
from qiskit.circuit.random import random_circuit
from qiskit.primitives import Estimator
from qiskit.providers import Backend
from qiskit.providers.fake_provider import ConfigurableFakeBackend
from qiskit.quantum_info.random import random_pauli_list
from quantum_serverless import QuantumServerless, get, distribute_task, put


@distribute_task()
def generate_circuits(
    depth_of_recursion: int, n_qubits: int, depth_of_circuit: int, n_circuits: int
):
    """Generates random circuits."""
    circuits = [random_circuit(n_qubits, depth_of_circuit) for _ in range(n_circuits)]
    if depth_of_recursion <= 1:
        return circuits
    else:
        return circuits + get(
            generate_circuits(
                depth_of_recursion - 1, n_qubits, depth_of_circuit, n_circuits
            )
        )


@distribute_task()
def generate_observables(
    depth_of_recursion: int, n_qubits: int, size: int, n_observables: int
):
    """Generated random observables."""
    observables = [random_pauli_list(n_qubits, size) for _ in range(n_observables)]
    if depth_of_recursion <= 1:
        return observables
    else:
        return observables + get(
            generate_observables(depth_of_recursion - 1, n_qubits, size, n_observables)
        )


@distribute_task()
def generate_data(
    depth_of_recursion: int,
    n_qubits: int,
    n_entries: int,
    circuit_depth: int = 2,
    size_of_observable: int = 2,
):
    return get(
        generate_circuits(
            depth_of_recursion=depth_of_recursion,
            n_qubits=n_qubits,
            n_circuits=n_entries,
            depth_of_circuit=circuit_depth,
        )
    ), get(
        generate_observables(
            depth_of_recursion=depth_of_recursion,
            n_qubits=n_qubits,
            size=size_of_observable,
            n_observables=n_entries,
        )
    )


def get_backends(n_backends: int, n_qubits: int):
    """Returns list of backends for program."""
    backend = ConfigurableFakeBackend("Tashkent", n_qubits=n_qubits, version=1)

    return [backend for _ in range(n_backends)]


@distribute_task()
def transpile_remote(
    circuits: List[QuantumCircuit], backend: Backend
) -> List[QuantumCircuit]:
    """Transpiles circuits against backend."""
    return transpile(circuits, backend)


@distribute_task()
def estimate(circuits: list, observables: list):
    """Estimates expectation values of given circuit."""
    return Estimator().run(circuits, observables).result()


@distribute_task()
def run_graph(
    depth_of_recursion: int,
    n_qubits: int,
    n_entries: int,
    circuit_depth: int,
    size_of_observable: int,
    n_backends: int,
):
    backends = get_backends(n_backends, n_qubits)

    circuits, observables = get(
        generate_data(
            depth_of_recursion=depth_of_recursion,
            n_qubits=n_qubits,
            n_entries=n_entries,
            circuit_depth=circuit_depth,
            size_of_observable=size_of_observable,
        )
    )

    observables_ref = put(observables)

    results = []
    for backend in backends:
        results.append(estimate(transpile_remote(circuits, backend), observables_ref))

    return get(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--depth_of_recursion",
        help="Depth of recursion in generating data.",
        default=3,
        type=int,
    )
    parser.add_argument(
        "--n_qubits", help="Number of qubits used in program.", default=2, type=int
    )
    parser.add_argument("--n_entries", help="Number of circuits.", default=10, type=int)
    parser.add_argument(
        "--circuit_depth", help="Depth of circuits.", default=3, type=int
    )
    parser.add_argument(
        "--size_of_observable",
        help="Size of observables in program.",
        default=3,
        type=int,
    )
    parser.add_argument("--n_backends", help="Number of backends", default=3, type=int)
    parser.add_argument(
        "--n_graphs", help="Number of graphs to run", default=1, type=int
    )

    args = parser.parse_args()

    with QuantumServerless().context():

        t0 = time.time()

        results = get(
            [
                run_graph(
                    depth_of_recursion=args.depth_of_recursion,
                    n_qubits=args.n_qubits,
                    n_entries=args.n_entries,
                    circuit_depth=args.circuit_depth,
                    size_of_observable=args.size_of_observable,
                    n_backends=args.n_backends,
                )
                for _ in range(args.n_graphs)
            ]
        )

        runtime = time.time() - t0

        print(f"Execution time: {runtime}")
        print(f"Results: {results}")
