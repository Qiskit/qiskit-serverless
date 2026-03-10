.. _deploy_image:

===============================
Deploy a Custom Function Image
===============================

This guide explains how to build and deploy a custom Docker image as a
``QiskitFunction``.

Anyone can deploy and run a custom image on a **local** Qiskit Serverless
cluster by setting ``provider="mockprovider"`` when initializing the
function. However, to deploy a custom image in a remote Qiskit Serverless
environment, you must be registered as a ``provider`` in that environment.

Both local and remote workflows follow four steps:

1. Implement the function entrypoint and Dockerfile
2. Build the image
3. Upload the image
4. Run the function

1. Implement function entrypoint and define Dockerfile
------------------------------------------------------

The source code from this section is available in ``docs/deployment/custom_function`` containing
``Sample-Dockerfile`` and ``runner.py``:

.. code-block::
   :caption: Custom image folder structure

   /custom_function
     runner.py
     Sample-Dockerfile

A custom function image must provide a ``Runner`` class with a ``run``
method, which is invoked during function execution. Its return value
becomes the function result.

Create ``runner.py``:

.. code-block::
   :caption: ``runner.py`` - Runner class entrypoint

   class Runner:
       def run(self, arguments: dict) -> dict:
           # Example implementation
           return {
               **arguments,
               "answer": 42
           }

Next, define a Dockerfile extending the base Qiskit Serverless ray node
image and adding your implementation:

.. code-block::
   :caption: Dockerfile for custom function image

   FROM icr.io/quantum-public/qiskit-serverless/ray-node:0.30.0

   USER 0
   WORKDIR /runner
   COPY ./runner.py /runner
   WORKDIR /
   USER 1000

For more complete examples, visit the :ref:`image_examples` section.

2. Build the Docker image
-------------------------

.. code-block::
   :caption: Build image

   docker build -t test-local-provider-function -f Sample-Dockerfile .

3. Upload the image
-------------------

For **local development using Docker**, update your ``docker-compose.yaml`` to use
the newly built image:

.. code-block::
   :caption: Modify Docker Compose

   services:
     ray-head:
       container_name: ray-head
       image: test-local-provider-function:latest

Run it:

.. code-block::
   :caption: Start Docker Compose

   docker-compose up

If using **Kubernetes in local development**, create the cluster and load the image:

.. code-block::
   :caption: Deploy and load image into Kind

   tox -e cluster-deploy
   kind load docker-image test-local-provider-function:latest

For **remote environments**, you must be a registered provider and
follow the provider upload workflow.

4. Run the function
-------------------

With the environment running, you just need to intantiate a service client (see :ref:`client_configuration`),
define a ``QiskitFunction`` that will use the custom image, upload it, and invoke it:

.. code-block::
   :caption: Uploading and running a function with a custom image

   from qiskit_serverless import QiskitFunction, ServerlessClient

   serverless = ServerlessClient(
       token="awesome_token",
       image="awesome_crn",
       host="http://localhost:8000", # Use http://localhost when using Kubernetes
   )

   function = QiskitFunction(
       title="custom-image-function",
       image="test-local-provider-function:latest",
       provider="mockprovider",
   )

   serverless.upload(function)
   my_function = serverless.get("custom-image-function")

   job = my_function.run(test_argument_one=1, test_argument_two="two")
   job.result()