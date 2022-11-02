# QuantumServerless Installation Guide

Project is arranged as monorepository. Each of sub-modules has it's own installation instructions.

## Client (QuantumServerless) library

```shell
pip install quantum_serverless
```

#### Installation from source

1. Run
```shell
cd client
pip install -e .
```

## Infrastructure

To follow the installation steps you will need the proper tools setup. We describe them in the infrastructure's [README](./infrastructure/readme.md):
1. Docker
2. Configure helm values
3. Terraform / Run helm

### Docker

First of all you will need to build the docker images inside the [docker folder](./infrastructure/docker/). You can follow the `docker build` examples described in the docker's README for that.

### Configure helm values

Once time you have your docker images built you must configure the values for helm. In the [values](./infrastructure/helm/quantumserverless/values.yaml) file you will find several placeholders where you can fill with the needed value what image you will use for each service.

For more information you have every variable described in the [README](./infrastructure//helm/quantumserverless/README.md) in case you need more configurations.

### Terraform / Run helm

At this step you are going to need to have decided where are you going to deploy the services. You have mostly two options:
1. Locally
2. Cloud provider

For the first one, **Locally**. You will need to have a k8s approach installed in your machine. You have several options for that: [Docker desktop](https://www.docker.com/products/docker-desktop/), [Minikube](https://minikube.sigs.k8s.io/docs/), [kind](https://kind.sigs.k8s.io/), [k3s](https://k3s.io/), etc...

If this is your case you just need to execute the helm configuration on you k8s instance following the installation step described in the helm's [README](./infrastructure/helm/quantumserverless/README.md).

If you are interested into manage the infrastructure in a **cloud provider** the project supports two of them, currently: [IBM Cloud](./infrastructure/terraform/ibm/), [AWS](./infrastructure/terraform/aws).

Once time you select one you will need to run the terraform configuration as is described in the terraform's [README](./infrastructure/terraform/README.md). Depending of the provider that you decide to use you will neeed to refer to the documentation of each provider to see if you need to configure something:
- [IBM Cloud](./infrastructure/terraform/ibm/README.md)
- [AWS](./infrastructure/terraform/aws/readme.md)

:warning: Each provider has a `values.yaml` with the configuration for the helm execution. In case you use `terraform` you will need to fill those files with the information from the [second step](#configure-helm-values).

## Manager

In-progress...
