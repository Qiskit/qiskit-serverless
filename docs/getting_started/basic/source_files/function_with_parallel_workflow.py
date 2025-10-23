"""function with parallel workflow for jupyter notebook."""
from qiskit_serverless import get_arguments, save_result, distribute_task, get

from qiskit import QuantumCircuit
from qiskit.providers import BackendV2
from qiskit.transpiler import generate_preset_pass_manager
from qiskit_ibm_runtime import SamplerV2 as Sampler


@distribute_task()
def distributed_sample(circuit: QuantumCircuit, backend: BackendV2):
    """Distributed task that returns quasi distribution for given circuit."""
    pm = generate_preset_pass_manager(backend=backend, optimization_level=3)
    isa_circuit = pm.run(circuit)
    return Sampler(backend).run([isa_circuit]).result()[0].data.meas.get_counts()


arguments = get_arguments()
circuits = arguments.get("circuits")
my_backend = arguments.get("backend")

# run distributed tasks as async function
# we get task references as a return type
sample_task_references = [distributed_sample(circuit, my_backend) for circuit in circuits]

# now we need to collect results from task references
results = get(sample_task_references)

save_result({"results": results})
