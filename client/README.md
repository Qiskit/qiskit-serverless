[![Stability](https://img.shields.io/badge/stability-alpha-f4d03f.svg)](https://github.com/Qiskit/qiskit-serverless/releases)
[![Client verify process](https://github.com/Qiskit/qiskit-serverless/actions/workflows/client-verify.yaml/badge.svg)](https://github.com/Qiskit/qiskit-serverless/actions/workflows/client-verify.yaml)
[![License](https://img.shields.io/github/license/qiskit-community/quantum-prototype-template?label=License)](https://github.com/qiskit-community/quantum-prototype-template/blob/main/LICENSE.txt)
[![Code style: Black](https://img.shields.io/badge/Code%20style-Black-000.svg)](https://github.com/psf/black)
[![Python](https://img.shields.io/badge/Python-3.11-informational)](https://www.python.org/)
[![Qiskit](https://img.shields.io/badge/Qiskit-%E2%89%A5%200.39.0-6133BD)](https://github.com/Qiskit/qiskit)

# Qiskit Serverless client

![diagram](https://raw.githubusercontent.com/Qiskit/qiskit-serverless/main/docs/images/qs_diagram.png)

# Installation

```shell
pip install qiskit_serverless
```

## Documentation

Full docs can be found at https://qiskit.github.io/qiskit-serverless/

## Usage

### Step 1: write funtion in ./src/function.py

```python
from qiskit_serverless import distribute_task, get, get_arguments, save_result

from qiskit import QuantumCircuit
from qiskit.circuit.random import random_circuit
from qiskit.primitives import StatevectorSampler as Sampler
from qiskit.quantum_info import SparsePauliOp

# 1. let's annotate out function to convert it
# to distributed async function
# using `distribute_task` decorator
@distribute_task()
def distributed_sample(circuit: QuantumCircuit):
    """Calculates quasi dists as a distributed function."""
    return Sampler().run([(circuit)]).result()[0].data.meas.get_counts()

# 2. our program will have one arguments
# `circuits` which will store list of circuits
# we want to sample in parallel.
# Let's use `get_arguments` funciton
# to access all program arguments
arguments = get_arguments()
circuits = arguments.get("circuits", [])

# 3. run our functions in a loop
# and get execution references back
function_references = [
    distributed_sample(circuit)
    for circuit in circuits
]

# 4. `get` function will collect all
# results from distributed functions
collected_results = get(function_references)

# 5. `save_result` will save results of program execution
# so we can access it later
save_result({
    "quasi_dists": collected_results
})
```


### Step 2: run function

```python
from qiskit_serverless import ServerlessClient, QiskitFunction
from qiskit.circuit.random import random_circuit

client = ServerlessClient(
    token="<TOKEN>",
    host="<GATEWAY_ADDRESS>",
)

# create function
function = QiskitFunction(
    title="Quickstart",
    entrypoint="program.py",
    working_dir="./src"
)
client.upload(function)

# create inputs to our program
circuits = []
for _ in range(3):
    circuit = random_circuit(3, 2)
    circuit.measure_all()
    circuits.append(circuit)

# run program
my_function = client.get("Quickstart")
job = my_function.run(circuits=circuits)
```

### Step 3: monitor job status

```python
job.status()
# 'DONE'

# or get logs
job.logs()
```


### Step 4: get results

```python
job.result()
# {'quasi_dists': [
# {'101': 902, '011': 66, '110': 2, '111': 37, '100': 17},
# {'100': 626, '101': 267, '001': 49, '000': 82},
# {'010': 145, '100': 126, '011': 127, '001': 89, '110': 173, '111': 166, '000': 94, '101': 104}
# ]}
```
