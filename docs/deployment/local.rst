.. _local_infrastructure:

==========================
Local infrastructure setup
==========================

Step 1: Create a Python environment and clone the repository

The ``qiskit-serverless`` repository contains some Dockerfiles which make spinning up a test cluster
on your local machine straightforward. The first thing we will do is clone the repository.

.. code-block::
   :caption: Create a minimal environment with only Python installed in it. We recommend using `Python virtual environments <https://docs.python.org/3.10/tutorial/venv.html>`_.

      python3 -m venv /path/to/virtual/environment

.. code-block::
   :caption: Activate your new environment.

      source /path/to/virtual/environment/bin/activate

.. code-block::
   :caption: Note: If you are using Windows, use the following commands in PowerShell.

      python3 -m venv c:\path\to\virtual\environment
      c:\path\to\virtual\environment\Scripts\Activate.ps1

.. code-block::
   :caption: Clone the Qiskit Serverless repository.

      cd /path/to/workspace/
      git clone git@github.com:Qiskit/qiskit-serverless.git

Step 2: Setup Docker

To setup Qiskit Serverless on your local machine, you will need to use docker compose. As we mentioned in the `README <https://github.com/Qiskit/qiskit-serverless/blob/main/README.md>`_
you can use any runtime that you prefer to run Docker on your machine: Docker Desktop, podman... 
If you are using a MacOS with ARM processors we highly recommend to use `Colima <https://github.com/abiosoft/colima>`_
as your container runtime to avoid problems with that architecture.

This is a project that takes advantage of distributed computing, so it places a high demand on resources. We recommend increasing the assigned resources to these runtimes. 
In case of Colima for example we typically use:

.. code-block::

        $ colima start --cpu 4 --memory 8 --disk 100

Step 2.1: Initiate the test environment

Once you have Docker and docker compose installed, you can run the following command from the root of the
``qiskit-serverless`` repository to set up the infrastructure:

.. code-block::

        $ docker compose [--profile <PROFILE>] up

Additionally, you can include the profile `full`.
With the full profile installs all core services, including logging and
monitorying systems.

Step 3: Setup Kind

Additionally we provide you a way to deploy a k8s cluster on your local machine. This has some benefits as this is a more similar environment 
to production than the docker-compose approach.

To simplify the process to deploy a k8s cluster locally we use `Kind <https://kind.sigs.k8s.io/docs/user/quick-start#installation>`_ 
as the main tool to create a cluster.

Step 3.1: Initiate the test cluster

To setup the cluster for testing we prepare a little script that will initialize for you all the needed resources. You can execute it
using the terminal just running the next command:

.. code-block::

        $ ./docs/deployment/custom_function/local_cluster/deploy.sh

Step 4: Run a program in the test environment

Once the containers are running, you can simulate a remote cluster with the resources on your
local machine. Feel free to go to our tutorials in the `Getting started section <https://qiskit.github.io/qiskit-serverless/getting_started/index.html>`_
and run some of them.


