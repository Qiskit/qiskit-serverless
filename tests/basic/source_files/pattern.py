from qiskit import QuantumCircuit
from qiskit.primitives import Sampler

from quantum_serverless import save_result

# all print statement will be available in job logs
print("Running pattern...")

# creating circuit
circuit = QuantumCircuit(2)
circuit.h(0)
circuit.cx(0, 1)
circuit.measure_all()

# running Sampler primitive
sampler = Sampler()
quasi_dists = sampler.run(circuit).result().quasi_dists

# saves results of program execution,
# which will be accessible by calling `.result()`
save_result(quasi_dists)
print("Completed running pattern.")
