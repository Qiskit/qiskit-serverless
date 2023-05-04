====================
Client configuration
====================

Quantum serverless has client-server architecture, which means
in order to interact with computational resources you need to have
client library installed on your machine and then configured to talk to computational resources.


Installation of client can be achieved by running

.. code-block::

        pip install quantum_serverless


Next we will need to configure our client to talk to computational resources.
This is happening through `Provider` configuration.

Before we configure our client and provider we need to know couple of things:
`username`/`password` a.k.a authentication details and `host` of our gateway server.

If you are using local docker-compose setup your user/password would be
`user`/`password123` and host would be http://gateway:8000.

If you are using cloud deployment your cloud administrator will provide details on host and authentication.

Will all necessary information in place we can start configuring our client

.. code-block::

		from quantum_serverless import QuantumServerless, GatewayProvider

		provider = GatewayProvider(
			username="<USERNAME>",
			password="<PASSWORD>",
			host="<HOST>",
		)

		client = QuantumServerless(provider)

With that you can run your programs against provider.

