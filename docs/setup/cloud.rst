==========================
Cloud infrastructure setup
==========================


``Quantum Serverless`` is a project that contains different resources. One of the most important ones is the ``client``
that you can connect with local and non-local resources.

The main purpose of this guide is explain you step by step how to deploy these resources to be able to load and use that
``client`` with your desired configuration.

So, you will be able to look up information in this guide for:

* :ref:`installation_requirements`
* Step by step commands to deploy using:
    * :ref:`docker-deployment`
    * :ref:`helm-deployment`
    * :ref:`terraform-deployment`

.. _installation_requirements:

Installation requirements
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

Docker: an easy to go option for local development
===================================================

This section will describe you the steps that you can follow to build and deploy the infrastructure with **Docker**.

If you have ``make`` available you can run the next commands in your terminal:

.. code-block::
   :caption: run the commands from the root of the project

        $ make build-notebook
        $ make build-ray-node

Or if you don't have it (Windows for example), you can always build the images manually:

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

Helm: to use your own cluster locally or in the cloud
=======================================================

Until now you deployed ``Quantum Serverless`` locally with a default configuration and minimum customization. With
**Helm** you are going to be able to deploy this project with a **production** ready configuration and fully
customizable on a local or cloud **k8s cluster**.

In this step your only requirement is to have a *k8s cluster* available. You have a tons of options for it:

* Docker desktop offers you a simple one. You just need to go to the "Docker desktop settings" > "Kubernetes section" and click in the option that says: "Enable Kubernetes".
* Create a cluster in a third party cloud service. Some examples from where you can take inspiration are:
    * `IBM Cloud cluster <https://cloud.ibm.com/docs/containers?topic=containers-clusters&interface=ui>`_
    * `Amazon EKS cluster <https://docs.aws.amazon.com/eks/latest/userguide/create-cluster.html>`_
    * `Azure AKS cluster <https://learn.microsoft.com/en-us/azure/aks/tutorial-kubernetes-deploy-cluster?tabs=azure-cli>`_

Once time you have your cluster the installation it's relatively easy with Helm. You just need to access to your cluster
and run the next commands:

.. code-block::
   :caption: run these commands from ./infrastructure/helm/quantumserverless folder

        $ helm repo add bitnami https://charts.bitnami.com/bitnami
        $ helm repo add kuberay https://ray-project.github.io/kuberay-helm
        $ helm dependency build
        $ helm -n <INSERT_YOUR_NAMESPACE> install quantum-serverless --create-namespace .

And this will deploy the required infrastructure in your cluster.

To connect with the different services you have some options depending of your environment. The easiest approach that
always will work is to use the ``port-forward`` command:

.. code-block::
   :caption: get kuberay-head and jupyter pods

        $ kubectl get pod -o wide
        $ > ...
        $ > <NAMESPACE>-jupyter-<POD_ID>
        $ > <NAMESPACE>-kuberay-head-<POD_ID>
        $ > ...

Now that we have the desired pods we can expose their ports:

.. code-block::
   :caption: ports 8265 and 8888 are the the default ports for each service

        $  kubectl port-forward <NAMESPACE>-kuberay-head-<POD_ID> 8265
        $  kubectl port-forward <NAMESPACE>-jupyter-<POD_ID> 8888

This way you will be able to access to your cluster services from localhost.

For development this is more than enough but if you are thinking in deploying in it somewhere probably you will need to
configure the different ``ingress`` properties in the `values.yaml <https://github.com/Qiskit-Extensions/quantum-serverless/blob/main/infrastructure/helm/quantumserverless/values.yaml>`_
of the project with the configuration of your domain and provider. In the ``Jupyter configs`` section you have a
configuration example to expose through ``ingress`` in ``localhost`` the Jupyter service (disabled by default).

* **Important**: ``nginx-ingress-controller`` is disabled by default because third party providers should provide its own Ingress controller. To use it locally you need to activate it too.

.. _terraform-deployment:

Terraform: deploy all the infrastructure in your favourite cloud provider
===========================================================================

This approach is very useful when you don't have anything where to deploy the infrastructure so let's go step by step.

Before anything the first thing that you should do is to create an account in your favourite cloud provider:
    * `IBM Cloud registration process <https://cloud.ibm.com/registration>`_
    * `AWS registration process <https://aws.amazon.com/premiumsupport/knowledge-center/create-and-activate-aws-account/>`_
    * Azure is not supported in this process by now but we have plans to include it soon.

Once time you have created an account, you will need to configure an API key/Access key to access from your terminal to your selected provider account:
    * `IBM Cloud API key creation <https://cloud.ibm.com/docs/account?topic=account-userapikey&interface=ui#create_user_key>`_
    * `AWS Access key creation <https://docs.aws.amazon.com/general/latest/gr/aws-sec-cred-types.html#access-keys-about>`_

And as last setup step install the provider's CLI:
    * `IBM Cloud CLI <https://cloud.ibm.com/docs/cli?topic=cli-getting-started>`_
    * `AWS CLI <https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html>`_

Now you have all the configuration needed from your cloud provider. The next step will be configure the terraform to
deploy the infrastructure where you want.

For that, depending of the provider, you need apply different configurations:

**For IBM Cloud** is the easiest one. Just go to ``./infrastructure/terraform/ibm`` and create the file ``terraform.tfvars``
with the next content:

.. code-block::

        ibmcloud_api_key = "YOUR_API_KEY"
        ibm_region = "YOUR_REGION"
        resource_group = "YOUR_RESOURCE_GROUP"

* **Note**: check in the next links to know the `region <https://cloud.ibm.com/docs/openwhisk?topic=openwhisk-cloudfunctions_regions>`_ and the `resource group <https://cloud.ibm.com/docs/account?topic=account-rgs&interface=cli>`_ that your account have configured.

**In AWS** case instead to create a file you will need to configure a set of environment variables in your terminal as it
is defined `here <https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-envvars.html#envvars-set>`_.

Once time your account is configured to be used by terraform just check that in your provider folder you have configured
your desired values for your services in ``values.yaml`` before the deployment process. To confirm the configuration
just run terraform:

.. code-block::
    :caption: always run a plan before an apply, this will compare your current configuration with the new one

        $ terraform plan

And as final step:

.. code-block::
    :caption: this command will deploy the plan in your account

        $ terraform apply

When the process finishes you should be able to see the cluster with the resources in your provider information:
    * `IBM Cloud cluster access guide <https://cloud.ibm.com/docs/containers?topic=containers-access_cluster>`_
    * `AWS cluster connection guide <https://aws.amazon.com/premiumsupport/knowledge-center/eks-cluster-connection/>`_

Quantum Serverless configuration
==================================

Once time you have your resources deployed it reaches the time to configure the ``Quantum Serverless client`` package.
It is easy to do with constructor arguments.

Let’s see how to do that.

First option is to pass configuration to constructor of ``QuantumServerless``:

.. code-block::
    :caption: constructor arguments example

        serverless = QuantumServerless({
            "providers": [{
                "name": "my_provider",  # provider name
                "compute_resource": { # main computational resource
                    "name": "my_resource", # cluster name
                    "host": "HOST_ADDRESS_OF_CLUSTER_HEAD_NODE", # cluster host address, if you are using helm it will be DEPLOYMENT_NAME-kuberay-head-svc
                }
            }]
        })

Other option will be creating an instance from configuration file, which has exactly the same structure as example
above.

.. code-block::
    :caption: config.json example

        {
            "providers": [{
                "name": "my_provider",
                "compute_resource": {
                    "name": "my_cluster",
                    "host": "HOST_ADDRESS_OF_CLUSTER_HEAD_NODE",
                }
            }]
        }

Then load this file:

.. code-block::
    :caption: verify the name and the path to load the file

        serverless = QuantumServerless.load_configuration("./config.json")

And use it as follow:

.. code-block::
    :caption: remember to use the same provider name

        with serverless.provider("my_provider"):
        ...
