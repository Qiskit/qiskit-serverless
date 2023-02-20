from qiskit import QuantumCircuit
from qiskit.primitives import Sampler

circuit = QuantumCircuit(2)
circuit.h(0)
circuit.cx(0, 1)
circuit.measure_all()
circuit.draw()

sampler = Sampler()

quasi_dists = sampler.run(circuit).result().quasi_dists

print(f"Quasi distribution: {quasi_dists[0]}")
