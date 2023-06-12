from qiskit import QuantumCircuit
from qiskit.primitives import Sampler

from quantum_serverless import save_result

print("Running program 1...")
circuit = QuantumCircuit(2)
circuit.h(0)
circuit.cx(0, 1)
circuit.measure_all()
circuit.draw()

sampler = Sampler()

quasi_dists = sampler.run(circuit).result().quasi_dists

save_result(quasi_dists)
print("Completed running program 1.")