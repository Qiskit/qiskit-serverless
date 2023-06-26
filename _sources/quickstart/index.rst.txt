==========
Quickstart
==========

.. note::

   These instructions describe a fully local workflow. To run on remote
   resources, users may either `configure their resources themselves <https://qiskit-extensions.github.io/quantum-serverless/deployment/cloud.html>`_ or ask
   their provider or dev ops team.

Step 0 [Optional]: Pre-Installation

.. code-block::
   :caption: Create a minimal environment with only Python installed in it. We recommend using `Python virtual environments <https://docs.python.org/3.10/tutorial/venv.html>`_.

      python3 -m venv /path/to/virtual/environment

.. code-block::
   :caption: Activate your new environment.

      source /path/to/virtual/environment/bin/activate

.. code-block::
   :caption: Note: If you are using Windows, use the following commands in PowerShell.

      python3 -m venv c:\path\to\virtual\environment
      c:\path\to\virtual\environment\Scripts\Activate.ps1

.. code-block::
   :caption: Clone the Quantum Serverless repository.

      cd /path/to/workspace/
      git clone git@github.com:Qiskit-Extensions/quantum-serverless.git

Step 1: Install Docker.

   If Docker is not installed on your system, following the directions
   on the `Docker website <https://docs.docker.com/engine/install/) to install Docker on your system>`_.

Step 2: Stop any running jupyter notebook servers.

Step 3: Install the quantum serverless package.

.. code-block::
   :caption: Install quantum_serverless via pip.

      pip install --upgrade pip
      pip install quantum_serverless


Step 4: Run infrastructure.

.. code-block::
   :caption: Run docker compose from the root of the quantum serverless project.
   
      cd quantum-serverless/
      docker compose --profile jupyter up

Step 5: Open the jupyter lab environment by going to ``localhost:8888`` via your favorite browser.

Step 6: Write your program in containerized environment.

.. code-block::
   :caption: Create a Python file using a text editor. Here we use vim.
   
      vim program.py

.. code-block:: python
   :caption: program.py

   from quantum_serverless import distribute_task, get, get_arguments, save_result

   from qiskit import QuantumCircuit
   from qiskit.circuit.random import random_circuit
   from qiskit.primitives import Sampler
   from qiskit.quantum_info import SparsePauliOp

   # 1. Define a distributed function using the `distribute_task` decorator
   @distribute_task()
   def distributed_sample(circuit: QuantumCircuit):
       """Calculates quasi dists as a distributed function."""
       return Sampler().run(circuit).result().quasi_dists[0]


   # 2. Get the program arguments using `get_arguments`
   arguments = get_arguments()
   circuits = arguments.get("circuits", [])

   # 3. Run the distributed function for each circuit in parallel and get execution references
   function_references = [
       distributed_sample(circuit)
       for circuit in circuits
   ]

   # 4. Collect all results using `get`
   collected_results = get(function_references)

   # 5. Save the results using `save_result`
   save_result({
       "quasi_dists": collected_results
   })

Step 5: Run the program.

.. code-block:: python
   :caption: in jupyter notebook

   from quantum_serverless import QuantumServerless, Provider, Program
   from qiskit.circuit.random import random_circuit

   serverless = QuantumServerless(Provider(
       username="user", # this username has already been defined in local docker setup and does not need to be changed
       password="password123", # this password has already been defined in local docker setup and does not need to be changed
       host="http://gateway:8000", # address of provider
   ))

   # create program
   program = Program(
       title="Quickstart",
       entrypoint="program.py",
       working_dir="./" # or where your program file is located
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

Step 6: Monitor the job status.

.. code-block:: python
   :caption: in jupyter notebook

   job.status()
   # <JobStatus.SUCCEEDED: 'SUCCEEDED'>

   job.logs()

Step 7: Get the results.

.. code-block:: python
   :caption: in jupyter notebook

   job.result()
   # {"quasi_dists": [
   #  {"0": 0.25, "1": 0.25, "2": 0.2499999999999999, "3": 0.2499999999999999},
   #  {"0": 0.1512273969460124, "1": 0.0400459556274728, "6": 0.1693190975212014, "7": 0.6394075499053132},
   #  {"0": 0.25, "1": 0.25, "4": 0.2499999999999999, "5": 0.2499999999999999}
   # ]}
