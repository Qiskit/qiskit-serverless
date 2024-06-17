==================================
Building custom image for function
==================================


In this tutorial we will describe how to build custom docker image for function.

In this tutorial we will be following 3 steps to deploy our function with custom docker image:

* implement function template 
* define dockerfile, build it and push to registry
* upload

All of our custom image files will be located in a folder `custom_function`, which will 2 files: `Dockerfile` and `runner.py`.

.. code-block::
   :caption: Custom image folder source files

   /custom_function
     /runner.py
     /Dockerfile

First we will implement function entrypoint by following template. All functions with custom docker images must follow same template structure. 

We need to create class `Runner` and implement `run` method that will be called during invocation of the function and results of the run method will be returned as result of the function.

Let's create `runner.py` file with following content

.. code-block::
   :caption: `runner.py` - Runner class implementation. This is an entrypoint to you custom image function.

    class Runner:
        def run(self, arguments: dict) -> dict:
            # this is just an example
            # your function can call for other modules, function, etc.
            return {
                **arguments,
                **{
                    "answer": 42
                }
            }


As a next step let's define and build our custom docker image.

Dockerfile will be extending base serverless node image and adding required packages and structure to it. 

In our simple case it will look something like this

.. code-block::
   :caption: Dockerfile for custom image function.

    FROM icr.io/quantum-public/qiskit-serverless-ray-node:0.12.0-py310

    # install all necessary dependencies for your custom image

    # copy our function implementation in `/runner.py` of the docker image
    USER 0

    WORKDIR /runner
    COPY ./runner.py /runner
    WORKDIR /

    USER $RAY_UID

and then we need to build it

.. code-block::
   :caption: Build and push image.

    docker build -t icr.io/quantum-public/my-custom-function-image:1.0.0 ./custom_function
    docker push icr.io/quantum-public/my-custom-function-image:1.0.0

We got to our final step of function development - uploading to serverless.

Let define `QiskitFunction` with image we just build, give it a name and upload it.

.. code-block::
   :caption: Uploading and using function with custom image.

    import os
    from qiskit_serverless import QiskitFunction, ServerlessClient

    serverless = ServerlessClient(
        token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
        host=os.environ.get("GATEWAY_HOST", "http://localhost:8000"),
    )
    serverless

    function_with_custom_image = QiskitFunction(
        title="custom-image-function",
        image="icr.io/quantum-public/my-custom-function-image:1.0.0"
        provider="mockprovider"
    )
    function_with_custom_image

    serverless.upload(function_with_custom_image)

    functions = {f.title: f for f in serverless.list()}
    my_function = functions.get("custom-image-function")
    my_function

    job = my_function.run(test_argument_one=1, test_argument_two="two")
    job

    job.result()

=============================
Example custom image function
=============================

Function example (runner.py)

.. code-block::
   :caption: runner.py

    from qiskit_aer import AerSimulator
    from qiskit_serverless import get_arguments, save_result
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

    def custom_function(arguments):
        service = arguments.get("service")
        circuit = arguments.get("circuit")
        observable = arguments.get("observable")
        backend = service.least_busy(operational=True, simulator=False, min_num_qubits=127)
        session = Session(backend=backend)

        target = backend.target
        pm = generate_preset_pass_manager(target=target, optimization_level=3)

        target_circuit = pm.run(circuit)
        target_observable = observable.apply_layout(target_circuit.layout)
 
        from qiskit_ibm_runtime import EstimatorV2 as Estimator
        estimator = Estimator(session=session)
        job = estimator.run([(target_circuit, target_observable)])

        session.close()
        return job.result()[0].data.evs

    class Runner:
        def run(self, arguments: dict) -> dict:
            return custom_function(arguments)

Dockerfile
	    
.. code-block::
   :caption: Dockerfile

    FROM icr.io/quantum-public/qiskit-serverless-ray-node:0.12.0-py310

    # install all necessary dependencies for your custom image

    # copy our function implementation in `/runner.py` of the docker image
    USER 0

    WORKDIR /runner
    COPY ./runner.py /runner
    WORKDIR /

    USER $RAY_UID

Build container image
    
.. code-block::
   :caption: Docker build

    Docker build -t function .
    Docker image tag function:latest "<image retistory/image name:image tag>"
    Docker image push "<image retistory/image name:image tag>"

The build container image need to be tagged and uploaded to the image registory that can be accessible from the gateway

Upload and register function
    
.. code-block::
   :caption: upload.py

    import os
    from qiskit_serverless import QiskitFunction, ServerlessClient

    serverless = ServerlessClient(
        token=os.environ.get("GATEWAY_TOKEN", "<TOKEN>"),
        host=os.environ.get("GATEWAY_HOST", "<GATEWAY ADDRESS>"),
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
        image="<image retistory/image name:image tag>",
        provider="<provider id>",
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
        token=os.environ.get("GATEWAY_TOKEN", "<TOKEN>"),
        host=os.environ.get("GATEWAY_HOST", "<GATEWAY ADDRESS>"),
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

    service = QiskitRuntimeService("YOUR_TOKEN")
    circuit = random_circuit(2, 2, seed=1234)
    observable = SparsePauliOp("IY")

    serverless = ServerlessClient(
        token=os.environ.get("GATEWAY_TOKEN", "<TOKEN>"),
        host=os.environ.get("GATEWAY_HOST", "<GATEWAY ADDRESS>"),
    )

    my_function = serverless.get("custom-image-function")
    job = my_function.run(service=service, circuit=circuit, observable=observable)

    print(job.result())
    print(job.logs())







