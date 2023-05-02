##################
Quantum serverless
##################

.. image:: /images/animation.gif

Quantum Serverless is a programming model for leveraging quantum and classical resources.

When to use quantum serverless? If you need to perform complex, long-running tasks on a regular basis.

Here are some reasons why:

1. `Remote scheduling`: When you have long running scripts/jobs that you want to run somewhere and get back results later.
Quantum serverless provides `asynchronous remote job execution`.

2. `Scalability`: Quantum Serverless allows users to easily scale their jobs by running them in parallel across multiple machines or general compute resources.
This can significantly improve performance and reduce the time it takes to complete a job.
So, when you hit resource limits of your local machine Quantum Serverless provides `horizontal scalability` of quantum and classical workloads.

3. `Workflow management`: Quantum Serverless provides a way to define and manage complex workflows of interdependent tasks,
making it easy to express complex problems in efficient modular way.

The source code to the project is available `on GitHub <https://github.com/Qiskit-Extensions/quantum-serverless>`_.

------------

.. toctree::
  :maxdepth: 2

  Quickstart <quickstart/index>

.. toctree::
  :maxdepth: 2

  Setup <setup/index>

.. toctree::
  :maxdepth: 2

  Running <running/index>

.. toctree::
  :maxdepth: 2

  Concepts <concepts/index>

.. toctree::
  :maxdepth: 2

  Development <development/index>

.. toctree::
  :maxdepth: 1

  API References <apidocs/index>

.. Hiding - Indices and tables
   :ref:`genindex`
   :ref:`modindex`
   :ref:`search`
