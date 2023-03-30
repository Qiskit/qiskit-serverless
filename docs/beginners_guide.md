# QuantumServerless Beginner's Guide

## About the Project
Today a lot of experiments are happening on a local machines or on manually allocated remote resources. This approach is not scalable and we need to give users tools to run hybrid workloads without worrying about allocating and managing underlying infrastructure. Moreover, the majority of code written today is not structured in a way to leverage parallel hybrid compute.

This project is aimed to give users a simple way of writing parallel hybrid code and scale it up on available hardware.

The project is structured as a monorepo, so it has 3 separate sub-modules:
- [client](../client)
- [manager](../manager)
- [infrastructure](../infrastructure)

## Installation

Refer to [installation guide](../INSTALL.md).

## Usage

Steps
1. prepare infrastructure
2. write your program
3. run program

#### Prepare infrastructure

In a root folder of this project you can find `docker-compose.yml` 
file, which is configured to run all necessary services for quickstart tutorials.

Run in a root folder
```shell
docker-compose pull
docker-compose up
```

#### Write your program

Create python file with necessary code. Let's call in `program.py`

```python
# program.py
from qiskit import QuantumCircuit
from qiskit.circuit.random import random_circuit
from qiskit.quantum_info import SparsePauliOp
from qiskit.primitives import Estimator

from quantum_serverless import QuantumServerless, run_qiskit_remote, get, put

# 1. let's annotate out function to convert it
# to function that can be executed remotely
# using `run_qiskit_remote` decorator
@run_qiskit_remote()
def my_function(circuit: QuantumCircuit, obs: SparsePauliOp):
    return Estimator().run([circuit], [obs]).result().values


# 2. Next let's create out serverless object to control
# where our remote function will be executed
serverless = QuantumServerless()

circuits = [random_circuit(2, 2) for _ in range(3)]

# 3. create serverless context
with serverless.context():
    # 4. let's put some shared objects into remote storage that will be shared among all executions
    obs_ref = put(SparsePauliOp(["ZZ"]))

    # 4. run our function and get back reference to it
    # as now our function it remote one
    function_reference = my_function(circuits[0], obs_ref)

    # 4.1 or we can run N of them in parallel (for all circuits)
    function_references = [my_function(circ, obs_ref) for circ in circuits]

    # 5. to get results back from reference
    # we need to call `get` on function reference
    print("Single execution:", get(function_reference))
    print("N parallel executions:", get(function_references))
```

#### Run program

Let's run our program now

```python
from quantum_serverless import QuantumServerless, GatewayProvider, Program

provider = GatewayProvider(
    username="user", # this username has already been defined in local docker setup and does not need to be changed
    password="password123", # this password has already been defined in local docker setup and does not need to be changed
    host="http://gateway:8000", # address of provider
)
serverless = QuantumServerless(provider)

# create out program
program = Program(
    name="my_program",
    entrypoint="program.py", # set entrypoint as out program.py file
    working_dir="./"
)

job = serverless.run_program(program)

job.status()
# <JobStatus.SUCCEEDED: 'SUCCEEDED'>

job.logs()
# Single execution: [1.]
# N parallel executions: [array([1.]), array([0.]), array([-0.28650496])]

job.result()
# '{"status": "ok", "single": [1.0], "parallel_result": [[1.0], [0.9740035726118753], [1.0]]}'
```



For more examples refer to [guides](./guides) and [tutorials](./tutorials).
