#!/usr/bin/env python

from qiskit import QuantumCircuit

circuit = QuantumCircuit(2)
circuit.h(0)
circuit.cx(0, 1)
circuit.measure_all()
circuit.draw()

from qiskit_serverless import ServerlessProvider, QiskitPattern
import os

serverless = ServerlessProvider(
    token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
    host=os.environ.get("GATEWAY_HOST", "http://localhost:8000"),
)
print(serverless)

pattern = QiskitPattern(
    title="pattern-with-arguments",
    entrypoint="pattern_with_arguments.py",
    working_dir="./source_files/",
)
serverless.upload(pattern)
job = serverless.run("pattern-with-arguments", arguments={"circuit": circuit})
print(job)

print(job.result())
print(job.status())
print(job.logs())
