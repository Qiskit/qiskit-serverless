.. _run_on_apple_silicon:

=========================================
Local development on Apple Silicon (arm64)
=========================================

The published ``ray-node`` image is built for ``linux/amd64`` only. On Apple Silicon
(M-series) Macs it therefore runs under QEMU emulation, which is slow enough that Ray 2.55's
dashboard startup does not finish within its hardcoded timeouts. The symptom is that the Ray
dashboard appears healthy but **jobs submitted to a local cluster stay stuck in** ``QUEUED``
(and eventually ``ERROR``), and the job never shows up in the Ray dashboard.

This page describes an alternative local-development path that builds and runs a **native
arm64** ``ray-node`` image. Because it runs natively (no emulation), Ray starts quickly and its
default timeouts are satisfied — without changing the Ray version or patching any timeouts.

.. note::

   This is a **local development** workaround for Apple Silicon only. Production and CI on
   native ``amd64`` hosts continue to use the official ``amd64`` images unchanged.

Symptom and root cause
----------------------

* **Symptom:** on an Apple Silicon Mac, ``job.result()`` never returns; the job sits in
  ``QUEUED`` and the scheduler logs show repeated package uploads to Ray while the Ray dashboard
  log shows ``POST /api/jobs/`` returning ``500`` after ~60s.
* **Cause:** Ray 2.55 starts several dashboard subprocess modules that must each report ready
  within hardcoded ~30s windows. Under QEMU emulation on arm64 these do not complete in time,
  so the jobs API is unavailable even though the dashboard HTTP port responds.
* **Fix:** run ``ray-head`` as a native arm64 image so startup is fast.

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

2. (Custom functions) build on the arm64 base
---------------------------------------------

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

3. Start the stack with the arm64 override
------------------------------------------

The repository ships ``docker-compose.arm64.yaml``, which runs ``ray-head`` natively on arm64
and keeps the ``gateway``, ``scheduler`` and ``postgres`` services on ``amd64`` (they contain no
Ray code and talk to ``ray-head`` over HTTP, so the mixed architecture is fine):

.. code-block::
   :caption: Start the stack on Apple Silicon

   VERSION=0.32.0 docker compose \
     -f docker-compose.yaml \
     -f docker-compose.arm64.yaml \
     up

If you built a custom function image (step 2), override the ``ray-head`` image with it — either
by editing ``docker-compose.arm64.yaml`` or via an additional override file — keeping
``platform: linux/arm64``.

With the stack running, upload and run your function as described in :ref:`deploy_image`; the job
should now progress ``QUEUED`` → ``DONE``.
