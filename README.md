[![Stability](https://img.shields.io/badge/stability-alpha-f4d03f.svg)](https://github.com/Qiskit-Extensions/quantum-serverless/releases)
[![License](https://img.shields.io/github/license/qiskit-community/quantum-prototype-template?label=License)](https://github.com/qiskit-community/quantum-prototype-template/blob/main/LICENSE.txt)
[![Code style: Black](https://img.shields.io/badge/Code%20style-Black-000.svg)](https://github.com/psf/black)
[![Python](https://img.shields.io/badge/Python-3.7%20%7C%203.8%20%7C%203.9%20%7C%203.10-informational)](https://www.python.org/)
[![Qiskit](https://img.shields.io/badge/Qiskit-%E2%89%A5%200.39.0-6133BD)](https://github.com/Qiskit/qiskit)

# Quantum serverless

Quantum Serverless is a user-friendly tool that enables you to easily run complex quantum computing tasks. 
With this software, you can execute Qiskit programs as long running jobs and distribute them across multiple CPUs, GPUs, and QPUs. 
This means you can take on more complex quantum-classical programs and run them with ease. 
You don't have to worry about configuration or scaling up computational resources, as Quantum Serverless takes care of everything for you. 

![diagram](./docs/images/qs_diagram.png)

### Table of Contents

1. [Installation](INSTALL.md)
2. [Quickstart](#quickstart-guide)
3. [Beginners Guide](docs/beginners_guide.md)
4. [Getting started](docs/getting_started/)
5. Modules:
   1. [Client](./client)
   2. [Infrastructure](./infrastructure)
6. [Tutorials](docs/tutorials/)
7. [Guides](docs/guides/)
8. [How to Give Feedback](#how-to-give-feedback)
9. [Contribution Guidelines](#contribution-guidelines)
10. [References and Acknowledgements](#references-and-acknowledgements)
11. [License](#license)

----------------------------------------------------------------------------------------------------

### Quickstart

1. Prepare local infrastructure
```shell
docker-compose pull
VERSION=nightly docker-compose --profile full up
```

2. Open jupyter notebook in browser at [http://localhost:8888/](http://localhost:8888/). Password for notebook is `123`
3. Explore 3 getting started tutorials.

For more detailed examples and explanations refer to the [Beginners Guide](docs/beginners_guide.md).

----------------------------------------------------------------------------------------------------

### How to Give Feedback

We encourage your feedback! You can share your thoughts with us by:
- [Opening an issue](https://github.com/Qiskit-Extensions/quantum-serverless/issues) in the repository


----------------------------------------------------------------------------------------------------

### Contribution Guidelines

For information on how to contribute to this project, please take a look at our [contribution guidelines](CONTRIBUTING.md).

----------------------------------------------------------------------------------------------------

### Deprecation Policy

This project is meant to evolve rapidly and, as such, do not follow [Qiskit's deprecation policy](https://qiskit.org/documentation/contributing_to_qiskit.html#deprecation-policy).  We may occasionally make breaking changes in order to improve the user experience.  When possible, we will keep old interfaces and mark them as deprecated, as long as they can co-exist with the new ones.  Each substantial improvement, breaking change, or deprecation will be documented in release notes.


----------------------------------------------------------------------------------------------------

## References and Acknowledgements
[1] Qiskit Terra \
    https://github.com/Qiskit/qiskit-terra

[2] Client for IBM Qiskit Runtime \
    https://github.com/Qiskit/qiskit-ibm-runtime


----------------------------------------------------------------------------------------------------

### License
[Apache License 2.0](LICENSE.txt)
