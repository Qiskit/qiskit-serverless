==================================
Building custom image for function
==================================

In this tutorial we will describe how you can build your custom docker image and execute it as
a Qiskit Function.

You will be following 3 steps to deploy it:

* implement function template
* define dockerfile, build it
* upload

You can find the example in `docs/deployment/custom_function`, which will have 2 files: `Sample-Dockerfile` and `runner.py`.

.. code-block::
   :caption: Custom image folder source files for the example

   /custom_function
     /runner.py
     /Sample-Dockerfile

First, you will implement your function entrypoint following the template. All functions with custom docker images must follow same template structure.

We need to create class `Runner` and implement `run` method that will be called during invocation of the function and the results of the run method will be returned as result of the function.

Let's create `runner.py` file with the following content:

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

In our simple case it will look something like this:

.. code-block::
   :caption: Dockerfile for custom image function.

    FROM icr.io/quantum-public/qiskit-serverless/ray-node:0.25.1

    # install all necessary dependencies for your custom image

    # copy our function implementation in `/runner/runner.py` of the docker image
    USER 0

    WORKDIR /runner
    COPY ./runner.py /runner
    WORKDIR /

    USER 1000

and after that we need to build it:

.. code-block::
   :caption: Build image

    docker build -t test-local-provider-function -f Sample-Dockerfile .

We got to our final step of function development - uploading to serverless.

For a local development you can modify `docker-compose.yaml` ray image with the image that it was generated in the previous step:

.. code-block::
   :caption: Modify docker compose definition

    services:
        ray-head:
            container_name: ray-head
            image: test-local-provider-function:latest

Run it:

.. code-block::
   :caption: Run docker compose

    docker-compose up

Or if you are using kubernetes you will need to create the cluster and load the image in Kind:

.. code-block::
   :caption: Run your local cluster
    
    tox -e cluster-deploy
    kind load docker-image test-local-provider-function:latest

And that's everything you need to take into account if you are using the k8s approach.

Once time the local environment is running, it only remains to run the code! For that you just need to define `QiskitFunction` 

with the image that you just built, give it a name and upload it:

.. code-block::
   :caption: Uploading and using function with custom image.

    import os
    from qiskit_serverless import QiskitFunction, ServerlessClient

    serverless = ServerlessClient(
        token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
        host=os.environ.get("GATEWAY_HOST", "http://localhost:8000"),
        # If you are using the kubernetes approach the URL must be http://localhost
    )
    serverless

    function = QiskitFunction(
        title="custom-image-function",
        image="test-local-provider-function:latest",
        provider="mockprovider"
    )
    function

    serverless.upload(function)

    my_function = serverless.get("custom-image-function")
    my_function

    job = my_function.run(test_argument_one=1, test_argument_two="two")
    job

    job.result()
