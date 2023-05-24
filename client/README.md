[![Stability](https://img.shields.io/badge/stability-alpha-f4d03f.svg)](https://github.com/Qiskit-Extensions/quantum-serverless/releases)
[![Client verify process](https://github.com/Qiskit-Extensions/quantum-serverless/actions/workflows/client-verify.yaml/badge.svg)](https://github.com/Qiskit-Extensions/quantum-serverless/actions/workflows/client-verify.yaml)
[![License](https://img.shields.io/github/license/qiskit-community/quantum-prototype-template?label=License)](https://github.com/qiskit-community/quantum-prototype-template/blob/main/LICENSE.txt)
[![Code style: Black](https://img.shields.io/badge/Code%20style-Black-000.svg)](https://github.com/psf/black)
[![Python](https://img.shields.io/badge/Python-3.7%20%7C%203.8%20%7C%203.9%20%7C%203.10-informational)](https://www.python.org/)
[![Qiskit](https://img.shields.io/badge/Qiskit-%E2%89%A5%200.39.0-6133BD)](https://github.com/Qiskit/qiskit)

# Quantum Serverless client

![diagram](https://raw.githubusercontent.com/Qiskit-Extensions/quantum-serverless/main/docs/images/qs_diagram.png)

# Installation

```shell
pip install quantum_serverless
```

## Documentation

Full docs can be found at https://qiskit-extensions.github.io/quantum-serverless/

## Usage

### Step 1: write program

```python
  from quantum_serverless import distribute_task, get, get_arguments, save_result

   from qiskit import QuantumCircuit
   from qiskit.circuit.random import random_circuit
   from qiskit.primitives import Sampler
   from qiskit.quantum_info import SparsePauliOp

   # 1. let's annotate out function to convert it
   # to distributed async function
   # using `distribute_task` decorator
   @distribute_task()
   def distributed_sample(circuit: QuantumCircuit):
       """Calculates quasi dists as a distributed function."""
       return Sampler().run(circuit).result().quasi_dists[0]


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
 

### Step 2: run program

```python
   from quantum_serverless import QuantumServerless, GatewayProvider
   from qiskit.circuit.random import random_circuit

   serverless = QuantumServerless(GatewayProvider(
       username="<USERNAME>", 
       password="<PASSWORD>",
       host="<GATEWAY_ADDRESS>",
   ))

   # create program
   program = Program(
       title="Quickstart",
       entrypoint="program.py",
       working_dir="./src"
   )

   # create inputs to our program
   circuits = []
   for _ in range(3):
       circuit = random_circuit(3, 2)
       circuit.measure_all()
       circuits.append(circuit)

   # run program
   job = serverless.run(
       program=program,
       arguments={
           "circuits": circuits
       }
   )
```

### Step 3: monitor job status

```python
   job.status()
   # <JobStatus.SUCCEEDED: 'SUCCEEDED'>
    
   # or get logs
   job.logs()
```


### Step 4: get results

```python
   job.result()
   # {"quasi_dists": [
   #  {"0": 0.25, "1": 0.25, "2": 0.2499999999999999, "3": 0.2499999999999999},
   #  {"0": 0.1512273969460124, "1": 0.0400459556274728, "6": 0.1693190975212014, "7": 0.6394075499053132},
   #  {"0": 0.25, "1": 0.25, "4": 0.2499999999999999, "5": 0.2499999999999999}
   # ]}
```
