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

    FROM icr.io/quantum-public/quantum-serverless-ray-node:0.11.0-py310

    # install all necessary dependencies for your custom image

    # copy our function implementation in `/runner.py` of the docker image
    COPY ./runner.py ./runner.py

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
    from quantum_serverless import QiskitFunction, ServerlessClient

    serverless = ServerlessClient(
        token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
        host=os.environ.get("GATEWAY_HOST", "http://localhost:8010"),
    )
    serverless

    function_with_custom_image = QiskitFunction(
        title="custom-image-function",
        image="icr.io/quantum-public/my-custom-function-image:1.0.0"
    )
    function_with_custom_image

    serverless.upload(function_with_custom_image)

    functions = {f.title: f for f in serverless.list()}
    my_function = functions.get("custom-image-function")
    my_function

    job = my_function.run(test_argument_one=1, test_argument_two="two")
    job

    job.result()
