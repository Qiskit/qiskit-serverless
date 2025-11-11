"""function with parallel workflow for jupyter notebook."""
from qiskit_serverless import get_arguments, save_result, distribute_task, get

from qiskit import QuantumCircuit
from qiskit.providers import BackendV2
from qiskit.providers.exceptions import QiskitBackendNotFoundError
from qiskit.transpiler import generate_preset_pass_manager
from qiskit_ibm_runtime import SamplerV2 as Sampler
from qiskit_ibm_runtime.fake_provider import FakeProviderForBackendV2


@distribute_task()
def distributed_sample(circuit: QuantumCircuit, backend: BackendV2):
    """Distributed task that returns quasi distribution for given circuit."""
    pm = generate_preset_pass_manager(backend=backend, optimization_level=3)
    isa_circuit = pm.run(circuit)
    return Sampler(backend).run([isa_circuit]).result()[0].data.meas.get_counts()


arguments = get_arguments()
circuits = arguments.get("circuits")
backend_name = arguments.get("backend_name")
service = arguments.get("service")

# verifying arguments types
if not isinstance(circuits, List):
    circuits = [circuits]

for circuit in circuits:
    if not isinstance(circuit, QuantumCircuit):
        raise ValueError("Each circuit in circuits must be QuantumCircuit.")
if not isinstance(backend_name, str):
    raise ValueError("backend_name must be str.")


if "fake" in backend_name.lower():
    service = FakeProviderForBackendV2()
if isinstance(service, (FakeProviderForBackendV2, QiskitRuntimeService)):
    try:
        backend = service.backend(backend_name)
    except QiskitBackendNotFoundError as e:
        raise ValueError(f"Error retrieving backend {backend_name}: {e}") from e
else:
    raise ValueError(f"A service of type `QiskitRuntimeService` is required for using the backend named {backend_name}.")

# run distributed tasks as async function
# we get task references as a return type
sample_task_references = [distributed_sample(circuit, backend) for circuit in circuits]

# now we need to collect results from task references
results = get(sample_task_references)

save_result({"results": results})
