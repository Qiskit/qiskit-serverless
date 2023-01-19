####################################
Guide: multi cloud deployment
####################################

``Quantum Serverless`` is a project that contains different resources. One of the most important ones is the ``client``.
As we saw in other guides like `configuring quantum serverless </guides/03_configuring-quantum-serverless.html>`_ we can
connect this library with local and non-local resources.

The main purpose of this guide is explain you step by step how to deploy these resources to be able to use that client
with your desired configuration.

So, you will be able to look up information in this guide for:

* :ref:`requirements_installation`
* Step by step commands to deploy using:
    * :ref:`docker-deployment`: for easy to go local developments.
    * :ref:`helm-deployment`: do you already have a cluster? Deploy it in your infrastructure.
    * :ref:`terraform-deployment`: you don't have anything? We provide you with all the configuration needed to deploy everything in your favorite cloud.
        * IBM Cloud
        * Amazon Web Services (AWS)

.. _requirements_installation:

Requirements installation
===========================

To deploy the required infrastructure by ``Quantum Serverless`` you need to have installed three main tools:

* `Docker <https://www.docker.com/>`_
* `Helm <https://helm.sh/>`_
* `Terraform <https://www.terraform.io/>`_

For both tools in their respectively webpages you have the required steps to install them in different OS: Windows, Mac
and Linux.

* **Important**: before download them check the versions `on our GitHub <https://github.com/Qiskit-Extensions/quantum-serverless/tree/main/infrastructure#tools>`_ of each tool to verify that you download a compatible version.

Once time you have these tools installed you can check the installation running the next commands in your terminal:

.. code-block::

        $ docker --version
        $ > Docker version X, build Y
        $
        $ helm version
        $ > version.BuildInfo{Version:"X", GitCommit:"Y", GitTreeState:"Z", GoVersion:"T"}
        $
        $ terraform version
        $ > Terraform X

If all the commands returns you something similar with the version that you downloaded congratulations, you have the
tools installed!

.. _docker-deployment:

Docker deployment
===========================

This section will describe you the steps that you can follow to build and deploy the infrastructure with **Docker**.

If you have ``make`` available you can run the next commands in your terminal:

.. code-block::
   :caption: run the commands from the root of the project

        $ make build-notebook
        $ make build-ray-node

or if you don't have it (Windows for example), you can always build the images manually:

.. code-block::
   :caption: run the commands from the root of the project

        $ docker build -t qiskit/quantum-serverless-notebook -f ./infrastructure/docker/Dockerfile-notebook .
        $ docker build -t qiskit/quantum-serverless-ray-node -f ./infrastructure/docker/Dockerfile-ray-qiskit .

Now that you have built the needed Docker images you can run **docker-compose** to deploy locally the project:

.. code-block::
   :caption: run the command from the root of the project

        $ docker-compose up

And once time finished the execution of the command if everything went well you are going to be able to open the browser
and have access to:

* Jupyter notebook: http://localhost:8888
* Ray dashboard: http://localhost:8265

.. _helm-deployment:

Helm deployment
===========================

Until now you deployed locally with a default configuration and minimum customization ``Quantum Serverless``. With
**Helm** you are going to be able to deploy this project with a **production** ready configuration and fully
customizable on a local or cloud **k8s cluster**.

In this step your only requirement is to have a *k8s cluster* available. You have a tons of options for it:

* Docker desktop offers you a simple one. You just need to go to the Docker desktop settings > Kubernetes section and
    click in the option that says: "Enable Kubernetes".

* Create a cluster in a third party cloud service. Some examples from where you can take inspiration are:
    * `Amazon EKS cluster <https://docs.aws.amazon.com/eks/latest/userguide/create-cluster.html>`_
    * `IBM Cloud cluster <https://cloud.ibm.com/docs/containers?topic=containers-clusters&interface=ui>`_

Once time you have your cluster the installation it's relatively easy with Helm. You just need to access to your cluster
and run the next commands:

.. code-block::
   :caption: run these commands from infrastructure/helm/quantumserverless folder

        $ helm dependency build
        $ helm -n <INSERT_YOUR_NAMESPACE> install quantum-serverless --create-namespace .

And this will deploy the required infrastructure in your cluster.

.. TODO: I can't connect here directly with the cluster without a port-forwarding. Check ports configuration before continue.

.. _terraform-deployment:

Terraform deployment
===========================

.. TODO: here will go documentation about terraform and create IBM Cloud and AWS accounts.
