"""function with arguments for jupyter notebook."""
import os
from qiskit import QuantumCircuit
from qiskit.providers.exceptions import QiskitBackendNotFoundError
from qiskit.transpiler import generate_preset_pass_manager
from qiskit_serverless import get_arguments, save_result
from qiskit_ibm_runtime import QiskitRuntimeService
from qiskit_ibm_runtime.fake_provider import FakeProviderForBackendV2
from qiskit_ibm_runtime import SamplerV2 as Sampler


# get all arguments passed to this function
arguments = get_arguments()

# Extract inputs we care about
circuit = arguments.get("circuit")
backend_name = arguments.get("backend_name")
service = arguments.get("service")

# Basic validation
if not isinstance(circuit, QuantumCircuit):
    raise ValueError("circuit must be QuantumCircuit.")
if not isinstance(backend_name, str):
    raise ValueError("backend_name must be str.")

# Choose a provider: fake provider for local testing, or a real servic
if "fake" in backend_name.lower():
    service = FakeProviderForBackendV2()
if isinstance(service, (FakeProviderForBackendV2, QiskitRuntimeService)):
    try:
        backend = service.backend(backend_name)
    except QiskitBackendNotFoundError as e:
        raise ValueError(f"Error retrieving backend {backend_name}: {e}") from e
else:
    try:
        service = QiskitRuntimeService(
            channel=os.environ.get("QISKIT_IBM_CHANNEL"),
            token=os.environ.get("QISKIT_IBM_TOKEN"),
            instance=os.environ.get("QISKIT_IBM_INSTANCE"),
            url=os.environ.get("QISKIT_IBM_URL"),
        )
        backend = service.backend(backend_name)
    except QiskitBackendNotFoundError as e:
        raise ValueError(f"The backend named {backend_name} couldn't be found.") from e
    except Exception as e:
        raise ValueError(
            f"`QiskitRuntimeService` couldn't be initialized with os environment variables: {e}."
        ) from e

# Match the run to the backend and transpile
sampler = Sampler(backend)
pm = generate_preset_pass_manager(backend=backend, optimization_level=3)
isa_circuit = pm.run(circuit)

# Execute and collect counts
quasi_dists = sampler.run([isa_circuit]).result()[0].data.meas.get_counts()

# saving results of the execution
save_result({"quasi_dists": quasi_dists})
