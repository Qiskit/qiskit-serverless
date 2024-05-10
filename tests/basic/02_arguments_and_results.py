#!/usr/bin/env python

from qiskit import QuantumCircuit

circuit = QuantumCircuit(2)
circuit.h(0)
circuit.cx(0, 1)
circuit.measure_all()
circuit.draw()

from qiskit_serverless import ServerlessClient, QiskitFunction
import os

serverless = ServerlessClient(
    token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
    host=os.environ.get("GATEWAY_HOST", "http://localhost:8000"),
)
print(serverless)

function = QiskitFunction(
    title="pattern-with-arguments",
    entrypoint="pattern_with_arguments.py",
    working_dir="./source_files/",
)
serverless.upload(function)

functions = {f.title: f for f in serverless.list()}
my_pattern_function = functions.get("pattern-with-arguments")
my_pattern_function

job = my_pattern_function.run(circuit=circuit)
print(job)

print(job.result())
print(job.status())
print(job.logs())
