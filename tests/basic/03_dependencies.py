#!/usr/bin/env python

from quantum_serverless import QiskitPattern

pattern = QiskitPattern(
    title="pattern-with-dependencies",
    entrypoint="pattern_with_dependencies.py",
    working_dir="./source_files/",
    dependencies=["qiskit-experiments==0.6.0"],
)

from quantum_serverless import ServerlessProvider
import os

serverless = ServerlessProvider(
    token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
    host=os.environ.get("GATEWAY_HOST", "http://localhost:8000"),
)
print(serverless)

from qiskit.circuit.random import random_circuit

circuit = random_circuit(2, 2)


serverless.upload(pattern)

job = serverless.run("pattern-with-dependencies", arguments={"circuit": circuit})
print(job)

print(job.result())
print(job.status())
print(job.logs())
