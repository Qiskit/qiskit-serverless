##################
Qiskit Serverless
##################

Qiskit Serverless is a programming model for leveraging quantum and classical resources.

.. image:: /images/animation.gif

It is particularly useful for performing complex, long-running tasks on a regular basis.

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
  Installation <installation/index>
  Getting started <getting_started/index>
  Examples <examples/index>
  Migration guides <migration/index>
  Deployment <deployment/index>

.. toctree::
  :maxdepth: 1

  API References <apidocs/index>

------------

The source code to the project is available `on GitHub <https://github.com/Qiskit/qiskit-serverless>`_.

.. Hiding - Indices and tables
   :ref:`genindex`
   :ref:`modindex`
   :ref:`search`

