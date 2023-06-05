# source_files/program_2.py

from quantum_serverless import get_arguments, save_result, distribute_task, get

from qiskit import QuantumCircuit
from qiskit.primitives import Sampler
from qiskit.circuit.random import random_circuit

@distribute_task()
def distributed_sample(circuit: QuantumCircuit):
    """Distributed task that returns quasi distribution for given circuit."""
    return Sampler().run(circuit).result().quasi_dists[0]


circuits = [random_circuit(2, 2) for _ in range(3)]
[circuit.measure_all() for circuit in circuits]


# run distributed tasks as async function
# we get task references as a return type
sample_task_references = [
    distributed_sample(circuit)
    for circuit in circuits
]

# now we need to collect results from task references
results = get(sample_task_references)

save_result({
    "results": results
})
