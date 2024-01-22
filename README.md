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

1. [Quickstart](#quickstart)
1. Modules
   1. [Client](./client)
   1. [Repository](./repository)
   1. [Charts](./charts)
1. [How to Give Feedback](#how-to-give-feedback)
1. [Contribution Guidelines](#contribution-guidelines)
1. [Deprecation Policy](#deprecation-policy)
1. [References and Acknowledgements](#references-and-acknowledgements)
1. [License](#license)

----------------------------------------------------------------------------------------------------

### Quickstart
This Quickstart section guides users to easily deploy QuantumServerless infrastructure and run a simple example.
For user convenience, this section assumes that users will deploy the infrastructure in a local environment using Docker and test examples within the deployed Jupyter notebook.

1. Prepare local QuantumServerless infrastructure
   1. Install Docker
      If Docker is not installed on your system, follow the directions on the [Docker website](https://docs.docker.com/engine/install/) to install Docker on your system.
   1. Install quantum-serverless on your local system (we recommend using a [virtual environment](https://docs.python.org/3/library/venv.html)).
      ```shell
      pip install quantum-serverless
      ```
      Optional: install [Jupyter Lab](https://jupyter.org/)
      ```shell
      pip install jupyterlab
      ```
   1. Clone the Quantum Serverless repository
      ```shell
      git clone https://github.com/Qiskit-Extensions/quantum-serverless.git
      ```
   1. Run QuantumServerless infrastructure
      Execute Docker Compose using the following commands.
      ```shell
      cd quantum-serverless/
      sudo docker compose up
      ```

      The output should resemble the following.
      ```
      ~/quantum-serverless$ sudo docker compose --profile jupyter up
      [+] Running 5/0
       ✔ Network public-quantum-serverless_safe-tier     Created                                           0.0s
       ✔ Container ray-head                              Created                                           0.0s
       ✔ Container public-quantum-serverless-postgres-1  Created                                           0.0s
       ✔ Container gateway                               Created                                           0.0s
       ✔ Container scheduler                             Created                                           0.0s
      Attaching to gateway, public-quantum-serverless-postgres-1, qs-jupyter, ray-head, scheduler
      ```


1. Launch JupyterLab environment.
   ```shell
   cd docs/getting_started/ # the directory with sample notebooks
   jupyter lab
   ```
   This will open the Jupyter Lab environment in your web browser.
1. Write your first example Qiskit Pattern.
   In the JupyterLab, create a new file, `pattern.py`, in the `work` directory. You can include any arbitrary Python code in your program, or you can use the
   [example Python file in this tutorial](https://github.com/Qiskit-Extensions/quantum-serverless/blob/main/docs/getting_started/basic/01_running_program.ipynb).

1. Run the program
   In the JupyterLab, create a new notebook in the same directory as your program, and execute [the tutorial code](https://github.com/Qiskit-Extensions/quantum-serverless/blob/main/docs/getting_started/basic/01_running_program.ipynb).

   You can check the job status and get the result.

   ```
   job.status()
   # 'DONE'

   job.logs()
   # 2023-09-21 03:48:40,286\tINFO worker.py:1329 -- Using address 172.18.0.4:6379 set in the environment variable RAY_ADDRESS\n2023-09-21 03:48:40,286\tINFO worker.py:1458 -- Connecting to existing Ray cluster at address: 172.18.0.4:6379...\n2023-09-21 03:48:40,295\tINFO worker.py:1633 -- Connected to Ray cluster. View the dashboard at \x1b[1m\x1b[32m172.18.0.4:8265 \x1b[39m\x1b[22m\n
   ```
   ```
   job.status()
   # '{"quasi_dists": [{"1": 0.5071335183298108, "5": 0.4334908044837378, "7": 0.0593756771864515}, {"1": 0.9161860602334094, "5": 0.0838139397665906}, {"2": 0.4999999999999999, "3": 0.4999999999999999}]}'
   ```

   That's all!

For more detailed examples and explanations refer to the [Guide](https://qiskit-extensions.github.io/quantum-serverless/index.html):

1. [Getting Started](https://qiskit-extensions.github.io/quantum-serverless/getting_started/index.html#)
1. [Example Qiskit Patterns](https://qiskit-extensions.github.io/quantum-serverless/examples/index.html)
1. [Infrastructure](https://qiskit-extensions.github.io/quantum-serverless/deployment/index.html)
1. [Migrating from Qiskit Runtime programs](https://qiskit-extensions.github.io/quantum-serverless/migration/index.html)

----------------------------------------------------------------------------------------------------

### How to Give Feedback

We encourage your feedback! You can share your thoughts with us by:
- Opening an [issue](https://github.com/Qiskit-Extensions/quantum-serverless/issues) in the repository


----------------------------------------------------------------------------------------------------

### Contribution Guidelines

For information on how to contribute to this project, please take a look at our [contribution guidelines](CONTRIBUTING.md).

----------------------------------------------------------------------------------------------------

### Deprecation Policy

This project is meant to evolve rapidly and, as such, do not follow [Qiskit's deprecation policy](https://qiskit.org/documentation/contributing_to_qiskit.html#deprecation-policy).  We may occasionally make breaking changes in order to improve the user experience.  When possible, we will keep old interfaces and mark them as deprecated, as long as they can co-exist with the new ones.  Each substantial improvement, breaking change, or deprecation will be documented in release notes.


----------------------------------------------------------------------------------------------------

## References and Acknowledgements
[1] Qiskit \
    https://github.com/Qiskit/qiskit

[2] Client for IBM Qiskit Runtime \
    https://github.com/Qiskit/qiskit-ibm-runtime


----------------------------------------------------------------------------------------------------

### License
[Apache License 2.0](LICENSE.txt)
