##################
Quantum serverless
##################

Quantum Serverless is a programming model for leveraging quantum and classical resources

.. image:: /images/qs_diagram.png

The source code to the project is available `on GitHub <https://github.com/Qiskit-Extensions/quantum-serverless>`_.

------------

**Quickstart**

Step 1: run infrastructure

.. code-block::
   :caption: run docker compose from a root of the project

      docker-compose pull
      docker-compose up

Step 2: write program

.. code-block:: python
   :caption: program.py

   from qiskit import QuantumCircuit
   from qiskit.circuit.random import random_circuit
   from qiskit.quantum_info import SparsePauliOp
   from qiskit.primitives import Estimator

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

Step 3: run program

.. code-block:: python
   :caption: in jupyter notebook

   from quantum_serverless import QuantumServerless, Program

   serverless = QuantumServerless({
       "providers": [{
           "name": "docker-compose",
           "compute_resource": {
               "name": "docker-compose",
               "host": "localhost", # using our docker-compose infrastructure
           }
       }]
   })
   serverless.set_provider("docker-compose") # set provider as docker-compose

   # create out program
   program = Program(
       name="my_program",
       entrypoint="program.py", # set entrypoint as out program.py file
       working_dir="./"
   )

   job = serverless.run_program(program)

   job.status()
   # <JobStatus.SUCCEEDED: 'SUCCEEDED'>

   job.logs()
   # Single execution: [1.]
   # N parallel executions: [array([1.]), array([0.]), array([-0.28650496])]

------------

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
