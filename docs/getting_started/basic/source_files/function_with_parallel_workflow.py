from qiskit_serverless import get_arguments, save_result, distribute_task, get

from qiskit import QuantumCircuit
from qiskit_ibm_runtime import SamplerV2 as Sampler
from qiskit.transpiler import generate_preset_pass_manager


@distribute_task()
def distributed_sample(circuit: QuantumCircuit, backend: BackendV2):
    """Distributed task that returns quasi distribution for given circuit."""
    pm = generate_preset_pass_manager(backend=backend, optimization_level=3)
    isa_circuit = pm.run(circuit)
    return Sampler(backend).run([isa_circuit]).result()[0].data.meas.get_counts()


arguments = get_arguments()
circuits = arguments.get("circuits")
backend = arguments.get("backend")

# run distributed tasks as async function
# we get task references as a return type
sample_task_references = [distributed_sample(circuit, backend) for circuit in circuits]

# now we need to collect results from task references
results = get(sample_task_references)

save_result({"results": results})
