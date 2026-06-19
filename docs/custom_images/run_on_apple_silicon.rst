.. _run_on_apple_silicon:

=========================================
Local development on Apple Silicon (arm64)
=========================================

The published ``ray-node`` image is built for ``linux/amd64`` only and with the latest Ray versions
(>2.55) it can show issues for local development on Apple Silicon Macs, where Ray startup times can get
too long and hit timeouts. The usual symptom is jobs not transitioning from ``QUEUED`` to ``DONE``.

This page describes an alternative local development path that builds and runs a **native
arm64** ``ray-node`` image that can be used as-is or for custom image development.

.. note::

   This is a **local development** workaround for Apple Silicon only. Production and CI on
   native ``amd64`` hosts continue to use the official ``amd64`` images unchanged.


1. Build the native arm64 base image
------------------------------------

This repository ships an arm64 variant of the base image, ``ray-node/Dockerfile.arm64``, and a
matching dependency file, ``ray-node/requirements-dynamic-dependencies-arm64.txt``. Build it from
the repository root:

.. code-block::
   :caption: Build the arm64 ray-node image

   docker build --platform linux/arm64 \
     -t custom-ray-node:0.32.0-arm64 \
     -f ray-node/Dockerfile.arm64 .

.. note::

   The arm64 dependency set omits ``ffsim`` and ``qiskit-addon-aqc-tensor`` because
   ``ffsim==0.0.60`` has no published arm64 wheel. If your function needs them, uncomment the
   Rust-toolchain block in ``ray-node/Dockerfile.arm64`` (so ``ffsim`` compiles from source) and
   restore those entries in ``requirements-dynamic-dependencies-arm64.txt``.

2. Choose your path
-------------------

From here there are two ways to use the arm64 base image, depending on whether you need to build
a local "provider" image or you are following the "custom function" path without a bespoke image.

Path 1 — Run the stack with the arm64 base image as-is
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you just need a working local cluster (for example to run custom functions),
use the arm64 base image directly. The repository ships ``docker-compose.arm64.yaml``, which runs
``ray-head`` natively on arm64 and keeps the ``gateway``, ``scheduler`` and ``postgres`` services
on ``amd64`` (they contain no Ray code and talk to ``ray-head`` over HTTP, so the mixed
architecture is fine):

.. code-block::
   :caption: Start the stack on Apple Silicon

   VERSION=0.32.0 docker compose \
     -f docker-compose.yaml \
     -f docker-compose.arm64.yaml \
     up

With the stack running, upload and run your function; the job should now progress
``QUEUED`` → ``DONE``.

Path 2 — Build a custom function image on the arm64 base
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you are following :ref:`deploy_image`, point your function's ``Sample-Dockerfile`` at the
arm64 base instead of the published ``icr.io`` image:

.. code-block::
   :caption: Sample-Dockerfile on the arm64 base

   FROM custom-ray-node:0.32.0-arm64

   USER 0
   WORKDIR /runner
   COPY ./runner.py /runner
   WORKDIR /
   USER 1000

Then build it as usual, e.g.
``docker build --platform linux/arm64 -t test-local-provider-function -f Sample-Dockerfile .``.

Start the stack with the arm64 override, overriding the ``ray-head`` image with your custom
function image — either by editing ``docker-compose.arm64.yaml`` or via an additional override
file — keeping ``platform: linux/arm64``:

.. code-block::
   :caption: Start the stack on Apple Silicon

   VERSION=0.32.0 docker compose \
     -f docker-compose.yaml \
     -f docker-compose.arm64.yaml \
     up

With the stack running, upload and run your function as described in :ref:`deploy_image`; the job
should now progress ``QUEUED`` → ``DONE``.
