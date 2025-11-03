"""function for jupyter notebook."""
from qiskit import QuantumCircuit
from qiskit.transpiler import generate_preset_pass_manager
from qiskit_ibm_runtime import SamplerV2 as Sampler
from qiskit_ibm_runtime.fake_provider import FakeVigoV2
from qiskit_serverless import save_result

# all print statement will be available in job logs
print("Running function...")

# Step 1: Create a Bell-state circuit
circuit = QuantumCircuit(2)
circuit.h(0)
circuit.cx(0, 1)
circuit.measure_all()

# Step 2: Transpile for a fake backend (for demonstration)
backend = FakeVigoV2()
pm = generate_preset_pass_manager(backend=backend, optimization_level=1)
isa_circuit = pm.run(circuit)

# Step 3: Run the Sampler primitive
sampler = Sampler(backend)
quasi_dists = sampler.run([isa_circuit]).result()[0].data.meas.get_counts()


# Step 4: Save results so they can be retrieved later by calling `.result()`
save_result(quasi_dists)
print("Completed running function.")
