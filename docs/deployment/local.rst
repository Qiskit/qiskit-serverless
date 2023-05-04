==========================
Local infrastructure setup
==========================

Local setup (on your notebook/machine) for quantum-serverless is configured using `docker-compose`_.

.. _docker-compose: https://docs.docker.com/compose/

Once you have docker and docker-compose install you can run instrastructure for quantum-serverless using following command.

.. code-block::

        $ VERSION=<VERSION> docker-compose [--profile <PROFILE>] up

Available profiles are `full` and `jupyter`.
`jupyter` profile will install core services and jupyter notebook.
`full` profile will install all core services, jupyter + logging and monitoring systems.

Available version can be found in `GitHub releases`_ page.

.. _GitHub releases: https://github.com/Qiskit-Extensions/quantum-serverless/releases

Having that in mind let's say we want to install version `0.0.7` with all services.
Then command will be

.. code-block::

        $ VERSION=0.0.7 docker-compose --profile full up