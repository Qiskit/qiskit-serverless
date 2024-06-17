from qiskit_serverless import distribute_task, get


@distribute_task()
def ultimate():
    return 42


result = get([ultimate() for _ in range(10)])

print(result)
