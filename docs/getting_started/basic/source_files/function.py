from qiskit_serverless import save_result
from qiskit import QuantumCircuit
from qiskit_ibm_runtime import SamplerV2 as Sampler
from qiskit_ibm_runtime.fake_provider import FakeAlmadenV2
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

# all print statement will be available in job logs
print("Running function...")

# Set up a simulated backend and create a Bell state circuit.
backend = FakeAlmadenV2()
ideal_qc = QuantumCircuit(2)
ideal_qc.h(0)
ideal_qc.cx(0, 1)
ideal_qc.measure_all()

# Transpile the ideal circuit to one optimized for the backend.
pm = generate_preset_pass_manager(optimization_level=1, backend=backend)
isa_qc = pm.run(ideal_qc)

# Run the circuit on the sampler and get the measurement counts.
sampler = Sampler(mode=backend)
job = sampler.run([isa_qc], shots=1024)
result = job.result()[0].data.meas.get_counts()

# Save the final result for the serverless job.
save_result(result)