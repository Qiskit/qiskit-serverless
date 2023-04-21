from quantum_serverless import distribute_task

from qiskit import transpile, QuantumCircuit
from qiskit.primitives import Sampler


@distribute_task()
def ditribute_sample(circuit: QuantumCircuit):
    sampler = Sampler()
    return sampler.run(circuit).result().quasi_dists[0]


@distribute_task()
def distributed_transpile(circuit: QuantumCircuit, seed: int):
    transpiled_circuit = transpile(circuit, seed_transpiler=seed, optimization_level=3)
    depth = transpiled_circuit.depth()
    return transpiled_circuit, depth
