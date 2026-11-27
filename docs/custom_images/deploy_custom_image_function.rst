.. _deploy_image:

===============================
Deploy a Custom Function Image
===============================

.. important::

   This guide covers both engines. The ``Runner`` class contract (step 1) and the
   ``QiskitFunction(image=..., provider=...)`` upload/run API (step 4) are identical for Ray and
   Fleets — only the base image in the Dockerfile changes (``ray-node`` vs. ``fleet-node:base``).
   Steps 2-3 (build and run locally) only have a documented path for Ray: the local Fleets mock
   stack (:ref:`fleets_integration_tests`) runs every job's command inside one fixed
   ``fleet-worker`` container and does not pull per-job images the way real Code Engine does, so
   a custom Fleets provider image can't be exercised locally today. To try one, build it, push it
   somewhere Code Engine can pull it, and upload it as a registered provider against a real
   environment. See :ref:`concepts` for how the two engines relate.

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

The source code from this section is available in ``docs/custom_images/custom_function`` containing
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

Next, define a Dockerfile extending the base image for the engine you're targeting and adding
your implementation. For **Ray**:

.. code-block::
   :caption: Dockerfile for custom function image (Ray)

   FROM icr.io/quantum-public/qiskit-serverless/ray-node:0.38.0

   USER 0
   WORKDIR /runner
   COPY ./runner.py /runner
   WORKDIR /
   USER 1000:1000

For **Fleets**, extend ``fleet-node:base`` instead — ``runner.py`` and the ``Runner`` class are
unchanged:

.. code-block::
   :caption: Dockerfile for custom function image (Fleets)

   FROM private.icr.io/quantum-public/qiskit-serverless/fleet-node:0.38.0

   USER 0
   WORKDIR /runner
   COPY ./runner.py /runner
   WORKDIR /
   USER 1000:1000

For more complete examples, visit the :ref:`image_examples` section.

2. Build the Docker image
-------------------------

.. code-block::
   :caption: Build image

   docker build -t test/local-provider-function -f Sample-Dockerfile .

3. Upload the image
-------------------

For **local development using Docker**, point the ``ray-head`` service in your
``docker-compose.yaml`` at the newly built image. Change **only** the ``image:`` line and
keep the rest of the existing ``ray-head`` definition (``user``, ``entrypoint``,
``environment``, ``ports``, ``volumes``, ``networks``) as-is:

.. code-block::
   :caption: Modify Docker Compose (only the image changes)

   services:
     ray-head:
       # keep the existing ray-head keys; only override the image
       image: test/local-provider-function:latest

Run it:

.. code-block::
   :caption: Start Docker Compose

   docker-compose up

.. note::

   On Apple Silicon (M-series) Macs, build your custom image on the native arm64 base and start
   the stack with the arm64 override — see :ref:`run_on_apple_silicon`. Otherwise jobs may hang
   in ``QUEUED``.

If using **Kubernetes in local development**, create the cluster and load the image:

.. code-block::
   :caption: Deploy and load image into Kind

   tox -e cluster-deploy
   kind load docker-image test/local-provider-function:latest

For **remote environments** (Ray or Fleets), you must be a registered provider. Push the image
somewhere the environment's runner can pull it from — the Ray cluster for a Ray provider, or Code
Engine for a Fleets provider — and upload your function with ``image=`` pointing at it, same as
step 4 below. There is no local Fleets equivalent to steps 2-3 above: see the note at the top of
this page.

4. Run the function
-------------------

With the environment running, you just need to instantiate a service client (see :ref:`client_configuration`),
define a ``QiskitFunction`` that will use the custom image, upload it, and invoke it:

.. code-block::
   :caption: Uploading and running a function with a custom image

   from qiskit_serverless import QiskitFunction, ServerlessClient

   serverless = ServerlessClient(
       token="awesome_token",
       instance="awesome_crn",
       host="http://localhost:8000", # Use http://localhost when using Kubernetes
   )

   function = QiskitFunction(
       title="custom-image-function",
       image="test/local-provider-function:latest",
       provider="mockprovider",
       runner="ray",  # defaults to "fleets"; this local stack only runs Ray
   )

   serverless.upload(function)
   my_function = serverless.get("custom-image-function", provider="mockprovider")

   job = my_function.run(test_argument_one=1, test_argument_two="two")
   job.result()