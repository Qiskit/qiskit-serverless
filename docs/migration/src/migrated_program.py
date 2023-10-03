"""A sample runtime program that submits random circuits for user-specified iterations."""

import random

from qiskit import transpile
from qiskit.circuit.random import random_circuit
from qiskit.primitives import Sampler

from quantum_serverless import get_arguments, save_result


def prepare_circuits():
    circuit = random_circuit(
        num_qubits=5, depth=4, measure=True, seed=random.randint(0, 1000)
    )
    return transpile(circuit)


arguments = get_arguments()
iterations = arguments.get("iterations", 5)

for it in range(iterations):
    qc = prepare_circuits()
    result = Sampler().run([qc]).result()
    print({"iteration": it, "dists": result.quasi_dists})

save_result({"result": "Hello, World!"})
