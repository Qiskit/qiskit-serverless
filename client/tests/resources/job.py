from quantum_serverless import QuantumServerless, distribute_task, get


@distribute_task()
def ultimate():
    return 42


with QuantumServerless().context():
    result = get([ultimate() for _ in range(10)])

print(result)
