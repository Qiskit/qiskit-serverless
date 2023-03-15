[![Stability](https://img.shields.io/badge/stability-alpha-f4d03f.svg)](https://github.com/Qiskit-Extensions/quantum-serverless/releases)
[![Repository verify process](https://github.com/Qiskit-Extensions/quantum-serverless/actions/workflows/repository-verify.yaml/badge.svg)](https://github.com/Qiskit-Extensions/quantum-serverless/actions/workflows/repository-verify.yaml)
[![License](https://img.shields.io/github/license/qiskit-community/quantum-prototype-template?label=License)](https://github.com/qiskit-community/quantum-prototype-template/blob/main/LICENSE.txt)
[![Code style: Black](https://img.shields.io/badge/Code%20style-Black-000.svg)](https://github.com/psf/black)
[![Python](https://img.shields.io/badge/3.8%20%7C%203.9%20%7C%203.10-informational)](https://www.python.org/)

# Quantum Serverless repository

Repository API for the quantum serverless project.
It manages the access to resources like: programs, users and authentication flow.

### Table of Contents

1. [Installation](#installation)
2. [Usage](#usage)

----------------------------------------------------------------------------------------------------

### Installation

```shell
pip install -U -r requirements.txt -r requirements-dev.txt
```

----------------------------------------------------------------------------------------------------

### Usage

To run the API you just need to run:

```shell
python manage.py runserver 
```

This command will run the API in port `8000`. 
If this is your first run you will need to apply the database changes first:

```shell
python manage.py migrate
```
