"""function with arguments for jupyter notebook."""
from qiskit import QuantumCircuit
from qiskit.providers.exceptions import QiskitBackendNotFoundError
from qiskit.transpiler import generate_preset_pass_manager
from qiskit_serverless import get_arguments, save_result
from qiskit_ibm_runtime import QiskitRuntimeService
from qiskit_ibm_runtime.fake_provider import FakeProviderForBackendV2
from qiskit_ibm_runtime import SamplerV2 as Sampler


# get all arguments passed to this function
arguments = get_arguments()

# get specific argument that we are interested in
circuit = arguments.get("circuit")
backend_name = arguments.get("backend_name")
service = arguments.get("service")

# verifying arguments types
if not isinstance(circuit, QuantumCircuit):
    raise ValueError("circuit must be QuantumCircuit.")
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

# matching our run to the backend argument
sampler = Sampler(backend)
pm = generate_preset_pass_manager(backend=backend, optimization_level=3)
isa_circuit = pm.run(circuit)

# running the circuit
quasi_dists = sampler.run([isa_circuit]).result()[0].data.meas.get_counts()

# saving results of the execution
save_result({
    "quasi_dists": quasi_dists
})
