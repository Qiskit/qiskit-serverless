=============================
Example custom image function
=============================

Function example (runner.py)

.. code-block::
   :caption: runner.py

   from qiskit_aer import AerSimulator
   from qiskit_serverless import get_arguments, save_result
   from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
   from qiskit_ibm_runtime import Session

   def custom_function(arguments):
        service = arguments.get("service")
        circuit = arguments.get("circuit")
        observable = arguments.get("observable")

        if service:
            backend = service.least_busy(operational=True, simulator=False, min_num_qubits=127)
            session = Session(backend=backend)
        else:
            backend = AerSimulator()

       target = backend.target
       pm = generate_preset_pass_manager(target=target, optimization_level=3)

       target_circuit = pm.run(circuit)
       target_observable = observable.apply_layout(target_circuit.layout)

       from qiskit_ibm_runtime import EstimatorV2 as Estimator
       if service:
           estimator = Estimator(session=session)
       else:
           estimator = Estimator(backend=backend)
       job = estimator.run([(target_circuit, target_observable)])

       if service:
           session.close()
       return job.result()[0].data.evs

   class Runner:
       def run(self, arguments: dict) -> dict:
           return custom_function(arguments)

Dockerfile

.. code-block::
   :caption: Dockerfile

   FROM icr.io/quantum-public/qiskit-serverless/ray-node:0.25.0

   # install all necessary dependencies for your custom image

   # copy our function implementation in `/runner/runner.py` of the docker image
   USER 0
   RUN  pip install qiskit_aer

   WORKDIR /runner
   COPY ./runner.py /runner
   WORKDIR /

   USER 1000

Build container image

.. code-block::
   :caption: Docker build

    docker build -t test-local-provider-function .

Prepare your local environment

.. code-block::
   :caption: Modify docker compose definition

    services:
        ray-head:
            container_name: ray-head
            image: test-local-provider-function:latest

Run it

.. code-block::
   :caption: Run docker compose

    docker-compose up

Or if you are using kubernetes you will need to create the cluster and load the image in Kind

.. code-block::
   :caption: Run your local cluster
    
    tox -e cluster-deploy
    kind load docker-image test-local-provider-function:latest

Run serverless

.. code-block::
   :caption: upload.py

   import os
   from qiskit_serverless import QiskitFunction, ServerlessClient

   serverless = ServerlessClient(
       token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
       host=os.environ.get("GATEWAY_HOST", "http://localhost:8000"),
       # If you are using the kubernetes approach the URL must be http://localhost
   )

   help = """

   title: custom-image-function

   description: sample function implemented in a custom image
   arguments:
       service: service created with the accunt information
       circuit: circuit
       observable: observable
   """

   function_with_custom_image = QiskitFunction(
       title="custom-image-function",
       image=test-local-provider-function:latest,
       provider=os.environ.get("PROVIDER_ID", "mockprovider"),
       description=help
   )
   serverless.upload(function_with_custom_image)

For the User

List all available functions

.. code-block::
   :caption: list.py

   import os
   from qiskit_serverless import ServerlessClient

   serverless = ServerlessClient(
       token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
       host=os.environ.get("GATEWAY_HOST", "http://localhost:8000"),
       # If you are using the kubernetes approach the URL must be http://localhost
   )

   my_functions = serverless.list()
   for function in my_functions:
       print("Name: " + function.title)
       print(function.description)
       print()

Execute Function

.. code-block::
   :caption: usage.py

   import os
   from qiskit_serverless import ServerlessClient
   from qiskit import QuantumCircuit
   from qiskit.circuit.random import random_circuit
   from qiskit.quantum_info import SparsePauliOp
   from qiskit_ibm_runtime import QiskitRuntimeService

   # set this True for the real Quantum system use
   use_service=False

   service = None
   if use_service:
       service = QiskitRuntimeService(
	   token=os.environ.get("YOUR_TOKEN", ""),
	   channel='ibm_quantum',
	   instance='ibm-q/open/main',
	   verify=False,
       )

   circuit = random_circuit(2, 2, seed=1234)
   observable = SparsePauliOp("IY")
   serverless = ServerlessClient(
       token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
       host=os.environ.get("GATEWAY_HOST", "http://localhost:8000"),
       # If you are using the kubernetes approach the URL must be http://localhost
   )

   my_function = serverless.get("custom-image-function")
   job = my_function.run(service=service, circuit=circuit, observable=observable)

   print(job.result())
   print(job.logs())
