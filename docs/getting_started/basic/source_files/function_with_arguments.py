from qiskit_serverless import get_arguments, save_result
from qiskit import QuantumCircuit
from qiskit_ibm_runtime import SamplerV2 as Sampler
from qiskit_ibm_runtime.fake_provider import FakeAlmadenV2
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

# Get the input circuit from arguments and set up a simulated backend.
arguments = get_arguments()
circuit = arguments.get("circuit")
backend = FakeAlmadenV2()

# Transpile the circuit to one optimized for the backend's hardware.
pm = generate_preset_pass_manager(optimization_level=1, backend=backend)
isa_qc = pm.run(circuit)

# Run the transpiled circuit on the sampler and get the measurement counts.
sampler = Sampler(mode=backend)
job = sampler.run([isa_qc], shots=1024)
result = job.result()[0].data.meas.get_counts()
print("\nMeasurement counts:", result)

# Save the final result for the serverless job.
save_result(result)