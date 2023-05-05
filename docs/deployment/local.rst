==========================
Local infrastructure setup
==========================

To set up Quantum Serverless on your local machine, you will need to use `docker-compose`_.

.. _docker-compose: https://docs.docker.com/compose/

Once you have Docker and docker-compose installed, you can run the following command to set up the infrastructure:

.. code-block::

        $ VERSION=<VERSION> docker-compose [--profile <PROFILE>] up

The available profiles are `full` and `jupyter`.
The jupyter profile installs core services and Jupyter Notebook,
while the full profile installs all core services,
Jupyter Notebook, and logging and monitoring systems.

Available version can be found in `GitHub releases`_ page.

.. _GitHub releases: https://github.com/Qiskit-Extensions/quantum-serverless/releases

For example, if you want to install version `0.0.7` with all services,
the command would be:

.. code-block::

        $ VERSION=0.0.7 docker-compose --profile full up