from qiskit import QuantumCircuit
from qiskit.circuit.random import random_circuit
from qiskit.quantum_info import SparsePauliOp
from qiskit.primitives import Estimator

from quantum_serverless import QuantumServerless, run_qiskit_remote, get, put, save_result

# 1. let's annotate out function to convert it
# to function that can be executed remotely
# using `run_qiskit_remote` decorator
@run_qiskit_remote()
def my_function(circuit: QuantumCircuit, obs: SparsePauliOp):
    """Compute expectation value of an obs given a circuit"""
    return Estimator().run([circuit], [obs]).result().values



# 2. Next let's create our serverless object that we will be using to create context
# which will allow us to run funcitons in parallel
serverless = QuantumServerless()

circuits = [random_circuit(2, 2) for _ in range(3)]

# 3. create serverless context which will allow us to run funcitons in parallel
with serverless.context():
    # 4. The observable is the same for all expectation value calculations. So we can put that object into remote storage since it will be shared among all executions of my_function.
    obs_ref = put(SparsePauliOp(["ZZ"]))

    # 5. we can run our function for a single input circuit 
    # and get back a reference to it as now our function is a remote one
    function_reference = my_function(circuits[0], obs_ref)

    # 5.1 or we can run N of them in parallel (for all circuits)
    function_references = [my_function(circ, obs_ref) for circ in circuits]

    # 6. to get results back from reference
    # we need to call `get` on function reference
    single_result = get(function_reference)
    parallel_result = get(function_references)
    print("Single execution:", single_result)
    print("N parallel executions:", parallel_result)

    # 6.1 (Optional) write results to db.
    save_result({
        "status": "ok",
        "single": single_result.tolist(),
        "parallel_result": [entry.tolist() for entry in parallel_result]
    })
