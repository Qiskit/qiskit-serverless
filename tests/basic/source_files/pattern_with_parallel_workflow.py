# source_files/program_with_parallel_workflow.py

from qiskit_serverless import get_arguments, save_result, distribute_task, get

from qiskit import QuantumCircuit
from qiskit.primitives import Sampler
from qiskit.circuit.random import random_circuit


@distribute_task()
def distributed_sample(circuit: QuantumCircuit):
    """Distributed task that returns quasi distribution for given circuit."""
    return Sampler().run(circuit).result().quasi_dists[0]


arguments = get_arguments()
circuits = arguments.get("circuits")

# run distributed tasks as async function
# we get task references as a return type
sample_task_references = [distributed_sample(circuit) for circuit in circuits]

# now we need to collect results from task references
results = get(sample_task_references)

save_result({"results": results})
