.. _concepts:

==========================
Concepts: Runners & Naming
==========================

This page explains two things: the two job execution engines (**Ray** and **Fleets**), and how
this SDK's class names map to the official terminology used on IBM's hosted service.

Execution engines: Ray vs. Fleets
----------------------------------

Jobs submitted through the gateway run on one of two engines:

* **Ray** — the original execution engine. It is being phased out in favor of Fleets. It is
  still what the Docker Compose and Kind setups in :ref:`local_setup` bring up, so most of the
  basic tutorials in this repo run against it.
* **Fleets** — built on IBM Cloud Code Engine. This is the engine behind IBM Quantum Functions
  (formerly Qiskit Functions), IBM's hosted managed-workflows service, and the one new work
  should target. See
  :ref:`fleets_tutorials` for a local, runnable walkthrough, and
  :ref:`fleets_integration_tests` for the stack it runs on.

The ``QiskitFunction``/``Runner`` API is the same for both engines — a provider function's
entrypoint contract and upload/run calls don't change (see :ref:`custom_images`). What's
engine-specific is the base container image (``ray-node`` vs. ``fleet-node``) and how much of
the workflow can be exercised fully from a local checkout: Fleets' local mock stand-in
(:ref:`fleets_integration_tests`) doesn't model per-job images, so a custom Fleets *provider
image* can only be tried against a real environment today, not locally.

A function doesn't choose its engine directly: which runner a job uses is a property of how the
function/provider is configured server-side.

Naming: this SDK vs. the official terminology
-----------------------------------------------

``qiskit_serverless`` (this package) exposes:

* ``QiskitFunction`` — a function/workload definition (entrypoint, working directory, optional
  container image).
* ``ServerlessClient`` — a client for a gateway you run yourself (local Docker Compose/Kind, or a
  self-hosted deployment).
* ``IBMServerlessClient`` — a ``ServerlessClient`` subclass preconfigured to talk to IBM's hosted
  service.

A ``QiskitFunction`` uploaded with no ``provider`` is what IBM's official docs call a **managed
workflow**. IBM's own client package, `qiskit-ibm-catalog
<https://quantum.cloud.ibm.com/docs/en/api/qiskit-ibm-catalog>`_, wraps these same SDK classes
under that official naming:

.. list-table::
   :header-rows: 1

   * - This SDK (``qiskit_serverless``)
     - Official name (``qiskit-ibm-catalog``)
   * - ``QiskitFunction``
     - ``ManagedWorkflow``
   * - ``IBMServerlessClient`` (via ``qiskit_ibm_catalog.QiskitServerless``)
     - ``ManagedWorkflowClient``
   * - ``IBMServerlessClient`` (via ``qiskit_ibm_catalog.QiskitFunctionsCatalog``, for
       catalog/vendor functions)
     - ``FunctionsCatalog``

This repository keeps the ``qiskit_serverless`` names in its own code and docs, since that's what
is actually importable from this package. For the official naming, the user-facing product
pages, and the supported way to run managed workflows against IBM's hosted service, see
`IBM Quantum: Managed workflows <https://quantum.cloud.ibm.com/docs/en/managed-workflows>`_.
