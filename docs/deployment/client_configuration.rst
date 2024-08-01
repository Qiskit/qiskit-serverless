====================
Client configuration
====================

Qiskit Serverless has a client-server architecture,
which means that in order to interact with computational
resources, you need to have the client library
installed on your machine and configured to communicate with the server.

To install the client library, run:

.. code-block::

        pip install qiskit-serverless


Next, we need to configure the client to communicate with the provider.
This can be done through the `ServerlessClient` configuration.

Before we can configure the client, we need to know two things: 
the `token` (authentication details) and the `host` of our gateway server.

If you are using the local docker compose setup,
your token would be `awesome_token` and the host would 
be `http://gateway:8000`.

If you are using `IBMServerlessClient`, you only need to pass the `tokne`.
What you can get it from https://quantum.ibm.com.

Once you have all the necessary information,
you can start configuring the client:

.. code-block::

		from qiskit_serverless import ServerlessClient

		client = ServerlessClient(
			token="<TOKEN>"
			host="<HOST>",
		)

With this configuration in place, you can run your Qiskit Functions.
