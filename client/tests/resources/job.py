from quantum_serverless import QuantumServerless, run_qiskit_remote, get


@run_qiskit_remote()
def ultimate():
    return 42


with QuantumServerless():
    result = get([ultimate() for _ in range(100)])

print(result)
