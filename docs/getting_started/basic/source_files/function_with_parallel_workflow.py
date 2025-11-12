"""function with parallel workflow for jupyter notebook."""
import os
from qiskit import QuantumCircuit
from qiskit.providers import BackendV2
from qiskit.providers.exceptions import QiskitBackendNotFoundError
from qiskit.transpiler import generate_preset_pass_manager
from qiskit_ibm_runtime import QiskitRuntimeService
from qiskit_ibm_runtime.fake_provider import FakeProviderForBackendV2
from qiskit_ibm_runtime import SamplerV2 as Sampler
from qiskit_serverless import get_arguments, save_result, distribute_task, get


@distribute_task()
def distributed_transpilation(
    circuit_idx: int, circuit: QuantumCircuit, target_backend: BackendV2
):
    """Distributed task that returns an ISA circuit ready for execution."""
    print(
        f"[distributed_transpilation] Start (index={circuit_idx}, "
        f"qubits={circuit.num_qubits}, clbits={circuit.num_clbits}, backend={target_backend.name})"
    )
    pm = generate_preset_pass_manager(backend=target_backend, optimization_level=3)
    isa_circuit = pm.run(circuit)
    print(f"[distributed_transpilation] Transpilation complete (index={circuit_idx})")
    return isa_circuit


# ----- parse inputs -----
# get all arguments passed to this function
print("[main] Parsing arguments...")
arguments = get_arguments()

# Extract inputs we care about
circuits = arguments.get("circuits")
backend_name = arguments.get("backend_name")
service = arguments.get("service")

# Normalize inputs
if circuits is None:
    raise ValueError(
        "`circuits` is required and must be a QuantumCircuit or a list of them."
    )
if not isinstance(circuits, list):
    circuits = [circuits]

# Basic validation
if not all(isinstance(circuit, QuantumCircuit) for circuit in circuits):
    raise ValueError("`circuits` must be a list of qiskit.QuantumCircuit objects.")
if not isinstance(backend_name, str):
    raise ValueError("backend_name must be a non-empty string.")

print(
    f"[main] Inputs received (num_circuits={len(circuits)}, backend_name={backend_name})"
)

# ----- resolve provider / backend -----
# Choose a provider: fake provider for local testing, or a real servic
if "fake" in backend_name.lower():
    print(
        "[main] Using fake provider (auto-selected because backend_name contains 'fake')."
    )
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
        print(
            f"[main] Runtime service initialized from env and backend "
            f"resolved (name={backend.name})"
        )
    except QiskitBackendNotFoundError as e:
        raise ValueError(f"The backend named {backend_name} couldn't be found.") from e
    except Exception as e:
        raise ValueError(
            f"`QiskitRuntimeService` couldn't be initialized with os environment variables: {e}."
        ) from e


# ----- launch parallel tasks -----

# get task references (async, parallel on the serverless cluster)
print(f"[main] Launching distributed transpilation tasks (count={len(circuits)})...")
# sending circuit indexing for
sample_task_references = [
    distributed_transpilation(idx, circuit, backend)
    for idx, circuit in enumerate(circuits)
]

# ----- collect ISA circuits -----
# collect all results (blocks until all tasks complete)
print("[main] Waiting for transpilation tasks to finish...")
isa_circuits = get(sample_task_references)
print(f"[main] All transpilation tasks completed (isa_count={len(isa_circuits)})")

# ----- batch execute on the quantum computer -----
print(f"[main] Executing circuits on backend (name={backend.name})...")
pub_results = Sampler(backend).run(isa_circuits).result()
print("[main] Circuit execution completed")

print("[main] Extracting counts from results...")
results = [r.data.meas.get_counts() for r in pub_results]

# ----- persist results -----
# persist results so `job.result()` returns them
save_result({"results": results})
print(
    "[main] Results saved (len(results) = "
    f"{len(results)}; example_keys={list(results[0].keys()) if results else '[]'})"
)
