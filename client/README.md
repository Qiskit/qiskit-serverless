[![License](https://img.shields.io/github/license/qiskit-community/quantum-prototype-template?label=License)](https://github.com/qiskit-community/quantum-prototype-template/blob/main/LICENSE.txt)
[![Code style: Black](https://img.shields.io/badge/Code%20style-Black-000.svg)](https://github.com/psf/black)
[![Python](https://img.shields.io/badge/Python-3.7%20%7C%203.8%20%7C%203.9%20%7C%203.10-informational)](https://www.python.org/)


# Quantum serverless client

Client part of quantum serverless project. 
Installable python library to communicate with provisioned infrastructure.

### Table of Contents

1. [Installation](#installation)
2. [Usage](#usage)

----------------------------------------------------------------------------------------------------

### Installation

```shell
pip install -e .
```

----------------------------------------------------------------------------------------------------


### Usage


```python
import ray
from quantum_serverless import QuantumServerless


@ray.remote(resources={"QPU": 1})
def code_that_need_to_be_executed_on_near_quantum_hardware():
    # Doing quantum things here!
    return "Quantum compute result"


@ray.remote
def code_that_need_to_be_executed_on_classical_nodes():
    # Doing classical things here!
    return "Classical compute result"


serverless = QuantumServerless()

print(f"Available clusters: {serverless.clusters()}")

# set cluster for context allocation
# by default 0 cluster (local) is selected
serverless.set_cluster(0)

with serverless.context():
    print(ray.get(code_that_need_to_be_executed_on_near_quantum_hardware.remote()))
    print(ray.get(code_that_need_to_be_executed_on_classical_nodes.remote()))

>>> Available clusters: [<Cluster[local_machine]: QPU 1>]
>>> Quantum compute result
>>> Classical compute result
```


