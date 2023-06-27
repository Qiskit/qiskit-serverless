====================
Client configuration
====================

Quantum Serverless has a client-server architecture,
which means that in order to interact with computational
resources, you need to have the client library
installed on your machine and configured to communicate with the provider.

To install the client library, run:

.. code-block::

        pip install quantum_serverless


Next, we need to configure the client to communicate with the provider.
This is done through the `Provider` configuration.

Before we can configure the client and provider,
we need to know two things: the `username/password`
(authentication details) and the `host` of our gateway server.

If you are using the local docker-compose setup,
your username and password would be `user` and `password123`,
respectively, and the host would be `http://gateway:8000`.

If you are using a cloud deployment, your cloud administrator
will provide you with the details of the host and authentication.

Once you have all the necessary information,
you can start configuring the client:

.. code-block::

		from quantum_serverless import QuantumServerless, Provider

		provider = Provider(
			username="<USERNAME>",
			password="<PASSWORD>",
			host="<HOST>",
		)

		client = QuantumServerless(provider)

With this configuration in place, you can run your programs
against the provider.
