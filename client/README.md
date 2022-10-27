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
pip install quantum_serverless
```

or local installation from source

```shell
pip install -e .
```

----------------------------------------------------------------------------------------------------


### Usage

```python
from quantum_serverless import QuantumServerless, run_qiskit_remote, get

# 1. let's annotate out function to convert it 
# to function that can be executed remotely
# using `run_qiskit_remote` decorator
@run_qiskit_remote()
def my_qiskit_function():
    # Doing compute things here!
    return "Computed result"


# 2. Next let's create out serverless object to control 
# where our remote function will be executed
serverless = QuantumServerless()

# 3. create serverless context
with serverless: # or serverless.provider("<NAME_OF_AVAILABLE_PROVIDER>")
    # 4. run our function and get back reference to it
    # as now our function it remote one
    function_reference = my_qiskit_function()
    # 4.1 or we can run N of them in parallel
    N = 4
    function_references = [my_qiskit_function() for _ in range(N)]

    # 5. to get results back from reference
    # we need to call `get` on function reference
    print(get(function_reference))
    print(get(function_references))
```
