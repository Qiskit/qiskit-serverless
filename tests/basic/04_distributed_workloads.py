#!/usr/bin/env python

from qiskit_serverless import ServerlessProvider
import os

serverless = ServerlessProvider(
    token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
    host=os.environ.get("GATEWAY_HOST", "http://localhost:8000"),
)
print(serverless)


from qiskit.circuit.random import random_circuit

circuits = [random_circuit(2, 2) for _ in range(3)]
[circuit.measure_all() for circuit in circuits]
print(circuits)


from qiskit_serverless import QiskitPattern

pattern = QiskitPattern(
    title="pattern-with-parallel-workflow",
    entrypoint="pattern_with_parallel_workflow.py",
    working_dir="./source_files/",
)

serverless.upload(pattern)

job = serverless.run("pattern-with-parallel-workflow", arguments={"circuits": circuits})
print(job)

print(job.result())
print(job.status())
print(job.logs())
