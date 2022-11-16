[![Stability](https://img.shields.io/badge/stability-alpha-f4d03f.svg)](https://github.com/Qiskit-Extensions/quantum-serverless/releases)
[![Client verify process](https://github.com/Qiskit-Extensions/quantum-serverless/actions/workflows/client-verify.yaml/badge.svg)](https://github.com/Qiskit-Extensions/quantum-serverless/actions/workflows/client-verify.yaml)
[![License](https://img.shields.io/github/license/qiskit-community/quantum-prototype-template?label=License)](https://github.com/qiskit-community/quantum-prototype-template/blob/main/LICENSE.txt)
[![Code style: Black](https://img.shields.io/badge/Code%20style-Black-000.svg)](https://github.com/psf/black)
[![Python](https://img.shields.io/badge/Python-3.7%20%7C%203.8%20%7C%203.9%20%7C%203.10-informational)](https://www.python.org/)
[![Qiskit](https://img.shields.io/badge/Qiskit-%E2%89%A5%200.39.0-6133BD)](https://github.com/Qiskit/qiskit)

# Quantum Serverless client

Client part of quantum serverless project. 
Installable python library to communicate with provisioned infrastructure.

### Table of Contents

1. [Installation](#installation)
2. [Usage](#usage)

----------------------------------------------------------------------------------------------------

### Installation

```shell
pip install quantum_serverless
```

or local installation from source

```shell
pip install -e .
```

----------------------------------------------------------------------------------------------------


### Usage

```python
from qiskit import QuantumCircuit
from qiskit.circuit.random import random_circuit
from qiskit.quantum_info import SparsePauliOp
from qiskit_ibm_runtime import Estimator

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
with serverless:
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
