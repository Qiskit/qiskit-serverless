from qiskit import QuantumCircuit
from qiskit.providers import BackendV2
from qiskit.transpiler import generate_preset_pass_manager
from qiskit_serverless import get_arguments, save_result
from qiskit_ibm_runtime import SamplerV2 as Sampler


# get all arguments passed to this function
arguments = get_arguments()

# get specific argument that we are interested in
circuit = arguments.get("circuit")
backend = arguments.get("backend")

# verifying arguments types
assert isinstance(circuit, QuantumCircuit)
assert isinstance(backend, BackendV2)

# matching our run to the backend argument
sampler = Sampler(backend)
pm = generate_preset_pass_manager(backend=backend, optimization_level=3)
isa_circuit = pm.run(circuit)

# running the circuit
quasi_dists = sampler.run([isa_circuit]).result()[0].data.meas.get_counts()

print(f"Quasi distribution: {quasi_dists}")

# saving results of the execution
save_result({
    "quasi_dists": quasi_dists
})
