# Quantum serverless deployment
Infrastructure part of quantum serverless project. Here you will find all the resources required to set up the correct environment to run the project.

### Requirements
- Helm >= 3.10

## Technologies

With these tools you will set up the infrastructure. Below the infrastructure the project makes use of [Ray](https://www.ray.io/) as the main framework to scale
the different Python executions that you can send to your [k8s](https://kubernetes.io/).

## Helm
In this folder you will find the main charts to set up your k8s cluster and the services that this project uses. There are 6 main services:
- **Jupyter**: this configuration deploys in your cluster the service that provides you with a notebook to work easily with the project.
- **Gateway**: this configuration deploys the API to handle your Ray cluster.
- **Scheduler**: inside the Gateway, this configuration deploys the Scheduler to manage Jobs execution and Ray Cluster creation.
- **Kuberay Operator**: a standard ray configuration to set up the KubeRay operator in the k8s cluster. This resource provides a Kubernetes-native way to manage Ray clusters.
- **Grafana / Prometheus**: a systems and service monitoring system. It collects metrics from configured targets at given intervals, evaluates rule expressions, displays the results, and can trigger alerts if some condition is observed to be true.

All the services are separated in two folders:
- **quantum-serverless**: that contains the core services to run it: gateway, operator, ray-cluster...
- **qs-observability**: optional services that helps to monitor `quantum-serverless`: grafana, prometheus...
