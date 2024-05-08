#!/usr/bin/env python

import os
from qiskit_serverless import ServerlessClient, distribute_qiskit_pattern, distribute_task, get, save_result, get_arguments
from qiskit.primitives import Sampler
from qiskit import QuantumCircuit
from qiskit.circuit.random import random_circuit

client = ServerlessClient(
    token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
    host=os.environ.get("GATEWAY_HOST", "http://localhost:8000"),
)
print(client)


@distribute_qiskit_pattern(client)
def hello_qiskit():
    circuit = QuantumCircuit(2)
    circuit.h(0)
    circuit.cx(0, 1)
    circuit.measure_all()
    circuit.draw()

    sampler = Sampler()
    quasi_dists = sampler.run(circuit).result().quasi_dists

    return quasi_dists


job = hello_qiskit()
print(job)
print(job.result())
print(job.status())
print(job.logs())


@distribute_task(target={"cpu": 1})
def distributed_sample(circuit: QuantumCircuit):
    """Distributed task that returns quasi distribution for given circuit."""
    return Sampler().run(circuit).result().quasi_dists


@distribute_qiskit_pattern(client)
def pattern_with_distributed_tasks(circuits):
    sample_task_references = [distributed_sample(circuit) for circuit in circuits]
    results = get(sample_task_references)
    print(results)


circuits = []
for _ in range(3):
    circuit = random_circuit(2, 2)
    circuit.measure_all()
    circuits.append(circuit)

job = pattern_with_distributed_tasks(circuits=circuits)
print(job)
print(job.result())
print(job.status())
print(job.logs())


@distribute_qiskit_pattern(client, working_dir="./")
def my_pattern_with_modules():
    quasi_dists = Sampler().run(create_hello_world_circuit()).result().quasi_dists
    return {"quasi_dists": quasi_dists}


job = my_pattern_with_modules()
print(job)
print(job.result())
print(job.status())
print(job.logs())
