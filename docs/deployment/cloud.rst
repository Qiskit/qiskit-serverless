==========================
Cloud infrastructure setup
==========================


``Qiskit Serverless`` is a project that contains different resources. One of the most important ones is the ``client``
that you can use to connect with local and non-local resources.

The main purpose of this guide is to explain to you, step-by-step, how to deploy these resources to be able to load and use that
``client`` with your desired configuration.

This guide contains:

* :ref:`installation_requirements`
* Step by step commands to deploy using:
    * :ref:`docker-deployment`
    * :ref:`helm-deployment`

.. _installation_requirements:

Installation requirements
=========================

To deploy the infrastructure required for ``Qiskit Serverless`` you need to have installed two main tools:

* `Docker <https://www.docker.com/>`_
* `Helm <https://helm.sh/>`_

Each of these tools' webpages contain instructions for installing on Windows, MacOS, and Linux.

Once you have these tools installed, you can check the installation by running the following commands in a terminal:

.. code-block::

        $ docker --version
        $ > Docker version X, build Y
        $
        $ helm version
        $ > version.BuildInfo{Version:"X", GitCommit:"Y", GitTreeState:"Z", GoVersion:"T"}


If all the commands return the correct versions, then congratulations, you have the tools installed!

.. _docker-deployment:

Docker: An easy option for local development
============================================

This section will describe the steps to build and deploy the infrastructure with **Docker**.

If you have ``docker compose`` available you can run the next command in your terminal:

.. code-block::
   :caption: run the command from the root of the project

        $ docker compose up

Once the execution of the command has finished, if everything went well you should be able to open the browser
and have access to the Ray dashboard at: http://localhost:8265

In case you want to use the ``main`` branch you can use the configuration for development running the next command:

.. code-block::
   :caption: run the command from the root of the project

        $ docker compose -f docker-compose-dev.yaml up

.. _helm-deployment:

Helm: Use your own cluster locally or in the cloud
==================================================

Until now you deployed ``Qiskit Serverless`` locally with a default configuration and minimum customization. With
**Helm** you are going to be able to deploy this project with a **production**-ready configuration and make it fully
customizable on a local or cloud **k8s cluster**.

In this step your only requirement is to have a *k8s cluster* available. You have a tons of options for it:

* Docker desktop offers you a simple one. You just need to go to the "Docker desktop settings" > "Kubernetes section" and click in the option that says: "Enable Kubernetes".
* Create a cluster in a third party cloud service. Some examples from where you can take inspiration are:
    * `IBM Cloud cluster <https://cloud.ibm.com/docs/containers?topic=containers-clusters&interface=ui>`_

Once your cluster is ready, the installation is relatively straightforward with Helm. To install a released version, You just need to access to your cluster
and run the next commands:

.. code-block::
   :caption: run this commands with the release version like 0.12.0 in x.y.z (2 places)

        $ helm -n <INSERT_YOUR_NAMESPACE> install qiskit-serverless --create-namespace https://github.com/Qiskit/qiskit-serverless/releases/download/vx.y.z/qiskit-serverless-x.y.z.tgz

This will deploy the required components to your cluster.

To connect with the different services, you have some options depending on your environment. The easiest and most consistent
approach is to use the ``port-forward`` command:

.. code-block::
   :caption: get gateway pod

        $ kubectl get service
        $ > ...
        $ > gateway ClusterIP 10.43.86.146 <none> 8000/TCP
        $ > ...

Now that we have the desired services, we can expose their ports:

.. code-block::
   :caption: ports 8265 and 8888 are the the default ports for each service

        $  kubectl port-forward service/gateway  3333:8000

Now you may access your cluster services from localhost.

For development this is more than enough, but if you are considering deploying it remotely you will need to
configure the various ``ingress`` properties in `values.yaml <https://github.com/Qiskit/qiskit-serverless/blob/main/charts/qiskit-serverless/values.yaml>`_
with the configuration of your domain and provider.

* **Important**: ``nginx-ingress-controller`` is disabled by default because third party providers should provide its own Ingress controller. To use it locally you need to activate it too.

Optionally, you can install an observability package to handle logging and monitoring on your cluster by running the following command:

.. code-block::
   :caption: run this commands with the release version like 0.12.0 in x.y.z (2 places) using the same namespace as in the previous helm command

        $ helm -n <INSERT_YOUR_NAMESPACE> install qs-observability  https://github.com/Qiskit/qiskit-serverless/releases/download/vx.y.z/qs-observability-x.y.z.tgz
