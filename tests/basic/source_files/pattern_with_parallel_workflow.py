# program.py

from qiskit_serverless import get_arguments, save_result, distribute_task, get

from qiskit import QuantumCircuit
from qiskit_ibm_runtime import SamplerV2 as Sampler
from qiskit_ibm_runtime.fake_provider import FakeAlmadenV2
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

# The @distribute_task decorator marks this function to be executed on a remote worker.
# It transpiles a circuit for a specific backend, runs it, and returns the results.
@distribute_task()
def distributed_compile_and_sample(ideal_circuit: QuantumCircuit, shots: int):
    """
    A distributed task that compiles a circuit for a specific backend ISA,
    runs it, and returns the measurement counts.
    """
    backend = FakeAlmadenV2()
    pm = generate_preset_pass_manager(optimization_level=1, backend=backend)
    sampler = Sampler(mode=backend)
    isa_circuit=pm.run(ideal_circuit)
    pub_result = sampler.run([isa_circuit], shots=shots).result()[0]
    return pub_result.data.meas.get_counts()


if __name__ == "__main__":
    # Get input arguments, which include a list of circuits to process.
    arguments = get_arguments()
    circuits = arguments.get("circuits")
    shots = arguments.get("shots", 4096) 

    # Submit a remote task for each circuit. This returns immediately with references to the tasks.
    task_references = [
        distributed_compile_and_sample(circuit, shots) for circuit in circuits
    ]

    # Wait for all the distributed tasks to complete and retrieve their results.
    results = get(task_references)
    
    # Save the final aggregated results.
    save_result({"results": results})