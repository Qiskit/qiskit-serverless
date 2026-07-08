.. _fleets_integration_tests:

========================
Fleets Integration Tests
========================

The fleets integration tests exercise the full IBM Code Engine (CE) *fleets*
execution path end to end — entirely on your machine, with no cloud account and
no cost. They are handy when you want to change or verify the fleets runner and
watch the whole job lifecycle work against a realistic stand-in for Code Engine.

How it works
------------

A small Docker Compose stack (``docker-compose-fleets-test.yaml``) starts the
real gateway and its dependencies, plus a **mock of Code Engine**:

* **gateway** and **scheduler** — the real Qiskit Serverless services, started
  with ``FLEETS_MOCK_ENABLED=1``. In this mode the gateway never calls IBM
  Cloud: the Code Engine client is swapped for a mock that writes a job
  *manifest* to object storage instead of creating a real CE fleet.
* **MinIO** — an S3-compatible server standing in for IBM Cloud Object Storage
  (COS). Job arguments, results, logs, and task state all live here.
* **fleet-worker** — a container that plays the role of a CE fleet worker: it
  polls object storage for job manifests, runs the job's command, and writes
  status and results back — mirroring how a real CE worker behaves.
* **postgres** — the gateway database.

A job follows the same path as in production, with the mock and worker standing
in for Code Engine:

.. code-block:: text

   client SDK ──▶ gateway ──▶ (mock) writes manifest ──▶ MinIO ──▶ fleet-worker
                                                                        │ runs job
        results / logs / status  ◀── MinIO ◀── worker writes ◀──────────┘

The tests drive the **real client SDK** against the gateway and assert the whole
job lifecycle through the client API, the database, and object storage. Results
and logs are retrieved exactly as in production: the gateway returns a presigned
object-storage URL that the client follows.

What is covered
---------------

* Uploading and running a custom (entrypoint) fleets function
* Running a provider (container-image) fleets function, including the split
  between public and provider-only logs
* A failing job (surfaced to the client as ``ERROR``)
* Cancelling a running job (surfaced as ``CANCELED``)

Running the tests
-----------------

**Prerequisites:** a Docker runtime with Compose (Docker or Podman), Python 3.11,
and ``tox``.

From the repository root:

.. code-block:: bash

   # 1. Build and start the stack (gateway, scheduler, postgres, MinIO, fleet-worker)
   docker compose -f docker-compose-fleets-test.yaml up --build -d

   # 2. Wait until the gateway is ready
   curl --retry 30 --retry-delay 2 --retry-all-errors --fail http://localhost:8000/liveness/

   # 3. Run the integration tests
   tox -c tests/tox.ini -e py311-fleets

   # 4. Tear down (``-v`` also removes the volumes)
   docker compose -f docker-compose-fleets-test.yaml down -v

The tests reach the gateway on port ``8000``, MinIO on ``9000``, and PostgreSQL
on ``5432`` — make sure those host ports are free before starting.

.. note::

   The first job after the stack starts pays a one-time cold-start cost while the
   scheduler and fleet-worker finish booting (the worker mounts object storage
   via s3fs). The suite warms the pipeline once before the timed tests, so that
   cost is absorbed up front instead of being charged to an individual test.

.. note::

   Podman works too — use ``podman compose`` (or ``podman-compose``) in place of
   ``docker compose``.
