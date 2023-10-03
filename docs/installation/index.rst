============
Installation
============

Step 0 [Optional]: Pre-Installation

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
   :caption: Clone the Quantum Serverless repository.

      cd /path/to/workspace/
      git clone git@github.com:Qiskit-Extensions/quantum-serverless.git

Step 1: Install the quantum serverless package.

.. code-block::
   :caption: Install quantum_serverless via pip.

      pip install --upgrade pip
      pip install quantum_serverless


Note: if you want to deploy your own infrastructure locally or in cloud environment, refer to this document :doc:`/deployment/local`.

