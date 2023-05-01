##################
Quantum serverless
##################

.. image:: /images/animation.gif

Quantum Serverless is a programming model for leveraging quantum and classical resources.

When to use quantum serverless? If you need to perform complex, long-running tasks on a regular basis.

Here are some reasons why:

1. `Remote scheduling`: When you have long running scripts/jobs that you want to run somewhere and get back results later.
Quantum serverless provides `asynchronous remote job execution`.

2. `Scalability`: Quantum Serverless allows users to easily scale their jobs by running them in parallel across multiple machines or general compute resources.
This can significantly improve performance and reduce the time it takes to complete a job.
So, when you hit resource limits of your local machine Quantum Serverless provides `horizontal scalability` of quantum and classical workloads.

3. `Workflow management`: Quantum Serverless provides a way to define and manage complex workflows of interdependent tasks,
making it easy to express complex problems in efficient modular way.

The source code to the project is available `on GitHub <https://github.com/Qiskit-Extensions/quantum-serverless>`_.

------------

**Quickstart**

Step 0: install package

.. code-block::
   :caption: pip install

      pip install quantum_serverless==0.0.7


Step 1: run infrastructure

.. code-block::
   :caption: run docker compose from a root of the project

      VERSION=0.0.7 docker-compose --profile full up


Step 2: write program

.. code-block:: python
   :caption: program.py

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

Step 3: run program

.. code-block:: python
   :caption: in jupyter notebook

   from quantum_serverless import QuantumServerless, GatewayProvider
   from qiskit.circuit.random import random_circuit

   serverless = QuantumServerless(GatewayProvider(
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
   job = serverless.run_program(
       program=program,
       arguments={
           "circuits": circuits
       }
   )

Step 4: monitor job status

.. code-block:: python
   :caption: in jupyter notebook

   job.status()
   # <JobStatus.SUCCEEDED: 'SUCCEEDED'>

   job.logs()

Step 5: get results

.. code-block:: python
   :caption: in jupyter notebook

   job.result()
   # {"quasi_dists": [
   #  {"0": 0.25, "1": 0.25, "2": 0.2499999999999999, "3": 0.2499999999999999},
   #  {"0": 0.1512273969460124, "1": 0.0400459556274728, "6": 0.1693190975212014, "7": 0.6394075499053132},
   #  {"0": 0.25, "1": 0.25, "4": 0.2499999999999999, "5": 0.2499999999999999}
   # ]}

------------

**Getting started**

.. toctree::
  :maxdepth: 2

  Guides <getting_started/index>

**Guides**

.. toctree::
  :maxdepth: 2

  Guides <guides/index>

**Tutorials**

.. toctree::
  :maxdepth: 2

  Tutorials <tutorials/index>

**API references**

.. toctree::
  :maxdepth: 1

  API References <apidocs/index>

.. Hiding - Indices and tables
   :ref:`genindex`
   :ref:`modindex`
   :ref:`search`
