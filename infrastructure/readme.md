# Quantum serverless deployment
Infrastructure part of quantum serverless project. Here you will find all the resources required to setup the correct environment to run the project.


## Tools

There are three main tools that you will need to install:
- [Docker](./docker)
- [Helm](./helm)
- [Terraform](./terraform)

### Requirements
- Docker >= 20.10
- Helm >= 3.10
- Terraform == 1.2.9


## Technologies

With these tools you will setup the infrastructure. Below the infrastructure the project makes use of [Ray](https://www.ray.io/) as the main framework to scale
the different Python executions that you can send to your [k8s](https://kubernetes.io/).


## Docker folder
In [this folder](./docker) you will find the resources related with the creation of the docker images that the infrastructure requires to deploy. There are two main images:
- Jupyter notebook: an image to be able to deploy a jupyter notebook in the infrastructure and make use of the project in a easy way without install anything locally.
- Ray: an image that contains the ray library to be used in the infrastructure.


## Helm folder
In [this folder](./helm) you will find the main configuration to setup your k8s cluster and the services that this project uses. There are 4 main configurations:
- **Jupyter**: this configuration deploys in your your cluster the service that provides you with a notebook to work easily with the project.
- **Middleware**: this configuration deploys the API to handle your Ray cluster.
- **Operator**: a standard ray configuration to setup the KubeRay operator in the k8s cluster. This resource provides a Kubernetes-native way to manage Ray clusters.
- **Ray cluster**: standard configuration to setup and deploy your Ray cluster in a k8s environment.


## Terraform
The [folder](./terraform) contains the configuration that helps you to create your k8s and Ray clusters. Currently the project supports deployments in:
- [IBM Cloud](https://cloud.ibm.com/login)
- [AWS](https://aws.amazon.com/)
