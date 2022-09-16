# Quantum Prototype Beginner's Guide

## About the Project
Today a lot of experiments are happening on a local machines or on manually allocated remote resources. This approach is not scalable and we need to give users tools to run hybrid workloads without worrying about allocating and managing underlying infrastructure. Moreover, the majority of code written today is not structured in a way to leverage parallel hybrid compute.

This project is aimed to give users a simple way of writing parallel hybrid code and scale it up on available hardware.

The project is structured as a monorepo, so it has 3 separate sub-modules:
- [client](../client)
- [middleware](../manager)
- [infrastructure](../infrastructure)

## Installation

Refer to [installation guide](../INSTALL.md).

## Usage

```python
from quantum_serverless import QuantumServerless, remote, get, put

@remote
def code_that_need_to_be_executed_on_nodes():
    # Doing compute things here!
    return "Compute result"


serverless = QuantumServerless()

print(f"Available clusters: {serverless.clusters()}")

# set cluster for context allocation
# by default 0 cluster (local) is selected
serverless.set_cluster(0)

with serverless.context():
    print(get(code_that_need_to_be_executed_on_nodes.remote()))

>>> Available clusters: [<Cluster: local>]
>>> Compute result
```

For more examples refer to [guides](./guides) and [tutorials](./tutorials).
