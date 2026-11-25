##################
Qiskit Serverless
##################

Qiskit Serverless is a programming model for leveraging quantum and classical resources.

.. image:: /images/animation.gif

It is particularly useful for performing complex, long-running tasks on a regular basis.

.. important::

   This site documents the ``qiskit-serverless`` **client SDK and self-hosted infrastructure**:
   installing the client, running your own gateway/Ray/Fleets stack, the gateway REST API, and
   contributing to the project. It is developer-facing, not the official user guide.

   If you want to use IBM's hosted service to run what this SDK calls a ``QiskitFunction``
   through ``IBMServerlessClient`` — officially branded as a **managed workflow** — the official
   docs and terminology live at
   `IBM Quantum: Managed workflows <https://quantum.cloud.ibm.com/docs/en/managed-workflows>`_,
   and the supported client there is
   `qiskit-ibm-catalog <https://quantum.cloud.ibm.com/docs/en/api/qiskit-ibm-catalog>`_, which
   wraps this SDK's classes as ``ManagedWorkflow`` and ``ManagedWorkflowClient``. See
   :ref:`concepts` for how the two map to each other.

Here are some reasons why you might want to consider using Qiskit Serverless:

`Scalability`: Qiskit Serverless allows users to easily scale their jobs by running them in
parallel across multiple machines or general compute resources.
This can significantly improve performance and reduce the time it takes to
complete a job. When you hit the resource limits of your local machine,
Qiskit Serverless provides horizontal scalability for both quantum and classical workloads.

`Remote execution`: Qiskit Serverless also provides asynchronous remote job execution,
making it ideal for long-running scripts or jobs that you want to run somewhere and
retrieve the results later. Users may upload compute-intensive scripts to a remote
system and receive the results when they are ready.

.. toctree::
  :maxdepth: 2

  About Qiskit Serverless <self>
  Concepts: Runners & Naming <concepts/index>
  Installation <installation/index>
  Local Setup <local_setup/index>
  Function Features <function_features/index>
  Custom Images <custom_images/index>
  Deployment <deployment/index>
  Gateway REST API <gateway_api/index>
  Release Notes <release-notes>

.. toctree::
  :maxdepth: 1

  API References <apidocs/index>

------------

The source code to the project is available `on GitHub <https://github.com/Qiskit/qiskit-serverless>`_.

.. Hiding - Indices and tables
   :ref:`genindex`
   :ref:`modindex`
   :ref:`search`

