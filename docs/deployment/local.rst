.. _local_infrastructure:

==========================
Local Infrastructure Setup
==========================

This guide walks you through setting up Qiskit Serverless on your local machine for development and testing.

Overview
--------

You can choose between two deployment approaches:

* **Docker Compose** (Recommended for beginners)

  - Fastest and simplest setup
  - Spins up containers for all services (gateway, scheduler, Ray)
  - Ideal for quick testing and development

* **Kind (Kubernetes-in-Docker)** (Advanced)

  - More closely resembles production environments
  - Useful for testing Kubernetes-specific behaviors
  - Requires more setup but provides better production parity

Prerequisites
-------------

Before you begin, ensure you have:

* **Python 3.10 or later**
* **Git**
* **Docker runtime** (required for both approaches)

  - `Colima <https://github.com/abiosoft/colima>`_ (recommended, especially for macOS with ARM processors)
  - `Docker Desktop <https://www.docker.com/products/docker-desktop/>`_
  - `Podman <https://podman.io/>`_

* **Docker Compose** (for Docker Compose approach)
* **Kind and kubectl** (for Kubernetes approach - Kind runs Kubernetes in Docker)

Step 1: Prepare Your Environment
---------------------------------

1.1 Create a Python Virtual Environment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

We recommend using Python virtual environments to isolate dependencies.

**On Linux/macOS:**

.. code-block:: bash

   python3 -m venv /path/to/virtual/environment
   source /path/to/virtual/environment/bin/activate

**On Windows (PowerShell):**

.. code-block:: powershell

   python3 -m venv c:\path\to\virtual\environment
   c:\path\to\virtual\environment\Scripts\Activate.ps1

For more information, see the `Python virtual environments documentation <https://docs.python.org/3.10/tutorial/venv.html>`_.

1.2 Clone the Repository
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   cd /path/to/workspace/
   git clone git@github.com:Qiskit/qiskit-serverless.git
   cd qiskit-serverless

Step 2: Install and Configure Docker Runtime
---------------------------------------------

Both deployment methods (Docker Compose and Kind) require a Docker runtime. We recommend **Colima**, especially for macOS with ARM processors, as it provides better performance and avoids architecture-related issues.

2.1: Install Docker Runtime
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Recommended: Colima**

Install Colima following the `installation guide <https://github.com/abiosoft/colima>`_.

**Alternative Options:**

* `Docker Desktop <https://www.docker.com/products/docker-desktop/>`_
* `Podman <https://podman.io/>`_

For more details, see the `project README <https://github.com/Qiskit/qiskit-serverless/blob/main/README.md>`_.

2.2: Start Docker with Adequate Resources
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Qiskit Serverless uses distributed computing and requires adequate resources:

* **CPU:** 4+ cores (minimum)
* **Memory:** 8+ GB (minimum)
* **Disk:** 100+ GB (minimum)

**For Colima:**

.. code-block:: bash

   colima start --cpu 4 --memory 8 --disk 100

Adjust these values based on your workload. For intensive computations, consider allocating more resources.

Step 3: Choose Your Deployment Method
--------------------------------------

Now that Docker is running, choose how you want to deploy Qiskit Serverless:

Option A: Docker Compose Setup (Recommended)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This is the fastest way to get started with Qiskit Serverless locally.

**3A.1: Start the Services**

From the repository root, run:

.. code-block:: bash

   docker compose up

This starts the core services. For additional services (logging, monitoring), use:

.. code-block:: bash

   docker compose --profile full up

The services will be available at:

* Gateway API: http://localhost:8000
* Ray Dashboard: http://localhost:8265 (if using local Ray)

Option B: Kind (Kubernetes) Setup (Advanced)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This approach deploys a local Kubernetes cluster, providing an environment closer to production.

**3B.1: Install Kind**

Follow the `Kind installation guide <https://kind.sigs.k8s.io/docs/user/quick-start#installation>`_.

**3B.2: Deploy the Cluster**

We provide a script that initializes all required resources:

.. code-block:: bash

   tox -e cluster-deploy

This command:

* Creates a Kind cluster (running in Docker)
* Deploys the Qiskit Serverless gateway
* Sets up Ray operator and clusters
* Configures networking

The services will be available at:

* Gateway API: http://localhost

Step 4: Verify Your Setup
--------------------------

Once your infrastructure is running, verify it's working correctly:

1. Check that all containers/pods are running:

   **Docker Compose:**

   .. code-block:: bash

      docker compose ps

   **Kind:**

   .. code-block:: bash

      kubectl get pods -A

2. Test the gateway API:

   .. code-block:: bash

      curl http://localhost:8000/health  # Docker Compose
      curl http://localhost/health        # Kind

Step 5: Configure the Client
-----------------------------

Now that your infrastructure is running, configure the Qiskit Serverless client to connect to it.

See the :ref:`client_configuration` guide for detailed instructions.

Quick example:

.. code-block:: python

   from qiskit_serverless import ServerlessClient

   client = ServerlessClient(
       token="awesome_token",
       instance="awesome_crn",
       host="http://localhost:8000",  # or "http://localhost" for Kind
   )

Step 6: Run Your First Function
--------------------------------

With everything set up, you're ready to run quantum functions!

Explore the :ref:`function_features` tutorials to learn how to:

* Create and upload functions
* Run distributed workloads
* Retrieve results
* And more

Next Steps
----------

* :ref:`function_features` - Learn how to build and run Qiskit Functions
* :ref:`client_configuration` - Detailed client configuration options
* :ref:`deployment` - Deploy to production environments (advanced)

Troubleshooting
---------------

**Services won't start:**

* Ensure Docker/Kind is running
* Check resource allocation (CPU, memory, disk)
* Review logs: ``docker compose logs`` or ``kubectl logs <pod-name>``

**Connection refused:**

* Verify the correct host URL (localhost:8000 for Docker Compose, localhost for Kind)
* Check firewall settings
* Ensure services are fully started (may take 1-2 minutes)

**Performance issues:**

* Increase allocated resources
* Close unnecessary applications
* Consider using the Docker Compose approach for lighter resource usage
