==========
Quickstart
==========

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
