#!/usr/bin/env python

from qiskit_serverless import ServerlessClient
import os

serverless = ServerlessClient(
    token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
    host=os.environ.get("GATEWAY_HOST", "http://localhost:8000"),
)
print(serverless)


from qiskit.circuit.random import random_circuit

circuits = [random_circuit(2, 2) for _ in range(3)]
[circuit.measure_all() for circuit in circuits]
print(circuits)


from qiskit_serverless import QiskitFunction

function = QiskitFunction(
    title="pattern-with-parallel-workflow",
    entrypoint="pattern_with_parallel_workflow.py",
    working_dir="./source_files/",
)
serverless.upload(function)

functions = {f.title: f for f in serverless.list()}
my_pattern_function = functions.get("pattern-with-parallel-workflow")
my_pattern_function

job = my_pattern_function.run(circuits=circuits)
print(job)

try:
  print(job.result())
except:
  print(job.error_message())

print(job.status())
print(job.logs())
