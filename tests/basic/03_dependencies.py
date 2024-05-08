#!/usr/bin/env python

from qiskit_serverless import QiskitFunction

function = QiskitFunction(
    title="pattern-with-dependencies",
    entrypoint="pattern_with_dependencies.py",
    working_dir="./source_files/",
    dependencies=["qiskit-experiments==0.6.0"],
)

from qiskit_serverless import ServerlessProvider
import os

serverless = ServerlessProvider(
    token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
    host=os.environ.get("GATEWAY_HOST", "http://localhost:8000"),
)
print(serverless)

from qiskit.circuit.random import random_circuit

circuit = random_circuit(2, 2)

serverless.upload(function)

functions = {f.title: f for f in serverless.list()}
my_pattern_function = functions.get("pattern-with-dependencies")
my_pattern_function

job = my_pattern_function.run(circuit=circuit)
print(job)

print(job.result())
print(job.status())
print(job.logs())
