"""function for jupyter notebook."""
from qiskit import QuantumCircuit
from qiskit.transpiler import generate_preset_pass_manager
from qiskit_ibm_runtime import SamplerV2 as Sampler
from qiskit_aer import AerSimulator
from qiskit_serverless import save_result

# all print statement will be available in job logs
print("Running function...")

# creating circuit
circuit = QuantumCircuit(2)
circuit.h(0)
circuit.cx(0, 1)
circuit.measure_all()

# Using AerSimulator for the example
backend = AerSimulator()
pm = generate_preset_pass_manager(backend=backend, optimization_level=1)
isa_circuit = pm.run(circuit)

# running Sampler primitive
sampler = Sampler(backend)
quasi_dists = sampler.run([isa_circuit]).result()[0].data.meas.get_counts()

# save results of function execution,
# which will be accessible by calling `.result()`
save_result(quasi_dists)
print("Completed running function.")
