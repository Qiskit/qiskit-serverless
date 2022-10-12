[![Build Status](https://travis.ibm.com/IBM-Q-Software/quantum-serverless.svg?token=8bkmZjRfW1zDMz5pG1sX&branch=main)](https://travis.ibm.com/IBM-Q-Software/quantum-serverless)
[![License](https://img.shields.io/github/license/qiskit-community/quantum-prototype-template?label=License)](https://github.com/qiskit-community/quantum-prototype-template/blob/main/LICENSE.txt)
[![Code style: Black](https://img.shields.io/badge/Code%20style-Black-000.svg)](https://github.com/psf/black)
[![Python](https://img.shields.io/badge/Python-3.7%20%7C%203.8%20%7C%203.9%20%7C%203.10-informational)](https://www.python.org/)


# Quantum serverless

### Table of Contents

1. [Installation](INSTALL.md)
2. [Beginners Guide](docs/beginners_guide.md)
3. [Quickstart Guide](docs/quickstart_guide.md)
4. Modules:
   1. [Client](./client)
   2. [Middleware](./manager)
   3. [Infrastructure](./infrastructure)
5. [Tutorials](docs/tutorials/)
6. [Guides](docs/guides/)
7. [How to Give Feedback](#how-to-give-feedback)
8. [Contribution Guidelines](#contribution-guidelines)
9. [References and Acknowledgements](#references-and-acknowledgements)
10. [License](#license)

----------------------------------------------------------------------------------------------------

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
with serverless:
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

----------------------------------------------------------------------------------------------------

### How to Give Feedback

We encourage your feedback! You can share your thoughts with us by:
- [Opening an issue](https://github.com/Qiskit-Extensions/quantum-serverless/issues) in the repository


----------------------------------------------------------------------------------------------------

### Contribution Guidelines

For information on how to contribute to this project, please take a look at our [contribution guidelines](CONTRIBUTING.md).


----------------------------------------------------------------------------------------------------

## References and Acknowledgements
[1] Qiskit Terra \
    https://github.com/Qiskit/qiskit-terra

[2] Client for IBM Qiskit Runtime \
    https://github.com/Qiskit/qiskit-ibm-runtime


----------------------------------------------------------------------------------------------------

### License
[Apache License 2.0](LICENSE.txt)