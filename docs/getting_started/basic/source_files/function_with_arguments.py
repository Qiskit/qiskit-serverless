"""function with arguments for jupyter notebook."""

import os
from qiskit import QuantumCircuit
from qiskit.providers.exceptions import QiskitBackendNotFoundError
from qiskit.transpiler import generate_preset_pass_manager
from qiskit_ibm_runtime import QiskitRuntimeService
from qiskit_ibm_runtime.fake_provider import FakeProviderForBackendV2
from qiskit_ibm_runtime import SamplerV2 as Sampler
from qiskit_serverless import get_arguments, save_result

# ----- parse inputs -----
# get all arguments passed to this function
print("[main] Parsing arguments...")
arguments = get_arguments()

# Extract inputs we care about
circuit = arguments.get("circuit")
backend_name = arguments.get("backend_name")
service = arguments.get("service")
print(f"[main] Inputs received (backend_name={backend_name})")

# Basic validation
if not isinstance(circuit, QuantumCircuit):
    raise ValueError("circuit must be QuantumCircuit.")
if not isinstance(backend_name, str) or len(backend_name) == 0:
    raise ValueError("backend_name must be a non-empty string.")

print(f"[main] Inputs received (backend_name={backend_name})")

# Choose a provider: fake provider for local testing, or a real servic
if "fake" in backend_name.lower():
    print("[main] Using fake provider (auto-selected because backend_name contains 'fake').")
    service = FakeProviderForBackendV2()

if isinstance(service, (FakeProviderForBackendV2, QiskitRuntimeService)):
    try:
        backend = service.backend(backend_name)
        print(f"[main] Backend resolved (name={backend.name})")
    except QiskitBackendNotFoundError as e:
        raise ValueError(f"Error retrieving backend {backend_name}: {e}") from e
else:
    # Fallback: build a Runtime service from environment variables
    print(
        "[main] No service provided and backend not fake; "
        "attempting to initialize QiskitRuntimeService from environment variables..."
    )

    try:
        service = QiskitRuntimeService(
            channel=os.environ.get("QISKIT_IBM_CHANNEL"),
            token=os.environ.get("QISKIT_IBM_TOKEN"),
            instance=os.environ.get("QISKIT_IBM_INSTANCE"),
            url=os.environ.get("QISKIT_IBM_URL"),
        )
        backend = service.backend(backend_name)
        print(f"[main] Runtime service initialized from env and backend " f"resolved (name={backend.name})")
    except QiskitBackendNotFoundError as e:
        raise ValueError(f"The backend named {backend_name} couldn't be found.") from e
    except Exception as e:
        raise ValueError(f"`QiskitRuntimeService` couldn't be initialized with os environment variables: {e}.") from e

# ----- transpile -----
# Match the run to the backend and transpile
print("[main] Building preset pass manager (optimization_level=3)...")
pm = generate_preset_pass_manager(backend=backend, optimization_level=3)
print("[main] Transpiling circuit...")
isa_circuit = pm.run(circuit)
print("[main] Transpilation complete")

# ----- execute -----
# Execute and collect counts
print(f"[main] Executing circuit on backend (name={backend.name})...")
sampler = Sampler(backend)
job_result = sampler.run([isa_circuit]).result()
print("[main] Sampler execution complete")

# Extract counts
quasi_dists = job_result[0].data.meas.get_counts()
print("[main] Extracted counts from result")

# ----- persist -------
# saving results of the execution
save_result({"quasi_dists": quasi_dists})
print("[main] Results saved.")
