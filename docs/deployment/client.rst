.. _client_configuration:

====================
Client Configuration
====================

Qiskit Serverless uses a client-server architecture. To access
computational resources, you must install the client library on your
machine and configure it to communicate with the server.

To install the client library from pip, run:

.. code-block::

    pip install qiskit-serverless

The library exposes two client classes: ``ServerlessClient`` and ``IBMServerlessClient``.

To configure the ``ServerlessClient``, you need three pieces of information:

* ``token`` - your authentication credential
* ``instance`` - your instance identifier
* ``host`` - the URL of the gateway server

The ``host`` parameter allows to set up the ``ServerlessClient`` to run on the
**local Docker Compose** setup (see :ref:`local_infrastructure` section).
To do so, use the following values:

* ``token``: ``"awesome_token"``
* ``instance``: ``"awesome_crn"``
* ``host``: ``"http://localhost:8000"``

If you are using the kubernetes approach the ``host`` URL must be ``"http://localhost"``

Once you have your credentials, configure the client:

.. code-block::

    from qiskit_serverless import ServerlessClient

    client = ServerlessClient(
        token="awesome_token",
        instance="awesome_crn",
        host="http://localhost:8000", # or "http://localhost"
    )

If you are using ``IBMServerlessClient``, the ``host`` is automatically set up to connect
to the Qiskit Functions service in IQP, and you only need to provide your IQP credentials,
which you can find in https://quantum.cloud.ibm.com.

.. code-block::

    from qiskit_serverless import IBMServerlessClient

    client = IBMServerlessClient(
        token="MY_IQP_API_KEY",
        instance="MY_IQP_CRN",
    )
