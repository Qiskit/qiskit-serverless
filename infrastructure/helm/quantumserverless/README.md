# Helm configuration

Main configuration to setup your k8s cluster and the services that this project uses. The helm configuration contains 4 charts: jupyter, manager, operator and ray-cluster.

## Installation

```shell
helm dependency build
```

```shell
helm -n ray install quantum-serverless --create-namespace .
```

Install from specific values file
```shell
 helm -n ray install quantum-serverless -f <PATH_TO_VALUES_FILE> --create-namespace .
```

## Helm chart values

**Redis**

For our Redis dependency we are using the configuration offered by Bitnami. To simplify the configuration we offered you with a straigh-forward initial parameters setup. But if you are interested in more complex configurations you have access to all the parameters that Bitnami added in the chart specified in their [README](https://artifacthub.io/packages/helm/bitnami/redis).

**Jupyter notebook**

| Name                      | Description                                                       |
|---------------------------|-------------------------------------------------------------------|
| jupyterEnable             | Specify if helm will execute the jupyter configuration.           |
| jupyter.jupyterToken      | Password for jupyter notebook.                                    |
| jupyter.image             | Docker image configuration to deploy the notebook.                |
| jupyter.imagePullSecrets  | Secrets to pull the image from a private registry.                |
| jupyter.container.port    | Port number that the pod will use in the cluster.                 |
| jupyter.service.port      | Port number that service will be exposed externally.              |
| jupyter.ingress.enabled   | Specifies if you are going to use ingress to expose the service.  |

**Manager**

| Name                       | Description                                                      |
|----------------------------|------------------------------------------------------------------|
| managerEnable              | Specify if helm will execute the manager configuration.          |
| manager.image              | Docker image configuration to deploy the manager.                |
| manager.imagePullSecrets   | Secrets to pull the image from a private registry.               |
| manager.container.port     | Port number that the pod will use in the cluster.                |
| manager.service.port       | Port number that service will be exposed externally.             |
| manager.ingress.enabled    | Specifies if you are going to use ingress to expose the service. |

**Ray cluster**

| Name                                      | Description                                                                                                                                                                   |
|-------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| rayClusterEnable                          | Specify if helm will execute the ray-cluster configuration.                                                                                                       |
| ray-cluster.image                         | Docker image configuration to deploy the manager.                                                                                                                 |
| ray-cluster.imagePullSecrets              | Secrets to pull the image from a private registry.                                                                                                                |
| ray-cluster.nameOverride                  | Replaces the name of the chart in the Chart.yaml.                                                                                                                 |
| ray-cluster.fullnameOverride              | Completely replaces the generated name.                                                                                                                           |
| ray-cluster.head                          | Head pod configuration which hosts global control processes for the Ray cluster.                                                                                  |
| ray-cluster.head.initArgs.dashboard-host  | Host to expose the Ray dashboard outside the Ray cluster.                                                                                                         |
| ray-cluster.head.initArgs.port            | Port to expose the Ray dashboard outside the Ray cluster.                                                                                                         |
| ray-cluster.worker                        | Worker pods configuration which run Ray tasks and actors.                                                                                                         |
| ray-cluster.worker.replicas               | Specifies the number of worker pods of that group to keep in the cluster. It has optional **minReplicas** and **maxReplicas** fields.                             |
| ray-cluster.ports                         | Port configuration for the worker.                                                                                                                                |
| ray-cluster.resources                     | Computational resources configuration for the worker.                                                                                                             |
| ray-cluster.headServiceSuffix             | Suffix used by the head service.                                                                                                                                  |
| ray-cluster.service.type                  | Options are ClusterIP, NodePort, and LoadBalancer. Exposing the head’s service outside the cluster may require using a service of type LoadBalancer or NodePort.  |
| ray-cluster.service.port                  | Port number that the head's service will be exposed externally.                                                                                                   |



**KubeRay operator**

| Name                          | Description                                                                                                                                                           |
|-------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| rayOperatorEnable             | Specify if helm will execute the kuberay-operator configuration.                                                                                                      |
| operator.image                | Docker image configuration to deploy the KubeRay Operator.                                                                                                            |
| operator.nameOverride         | Replaces the name of the chart in the Chart.yaml.                                                                                                                     |
| operator.fullnameOverride     | Completely replaces the generated name.                                                                                                                               |
| operator.rbac.true            | Specifies whether you want to install the default RBAC roles and bindings.                                                                                            |
| operator.serviceAccount.true  | Specifies whether a service account should be created.                                                                                                                |
| operator.serviceAccount.name  | The name of the service account to use.                                                                                                                               |
| operator.service.type         | Options are ClusterIP, NodePort, and LoadBalancer. Exposing the operators’ service outside the cluster may require using a service of type LoadBalancer or NodePort.  |
| operator.service.port         | Port number that the operators' service will user.                                                                                                                    |
| operator.ingress.enabled      | Specifies if you are going to use ingress to expose the service.                                                                                                      |
| operator.livenessProbe        | Liveness probe configuration.                                                                                                                                         |
| operator.readinessProbe       | Readiness probe configuration.                                                                                                                                        |
| operator.createCustomResource | Specifies whether helm should create a custom resource.                                                                                                               |
| operator.rbacEnable           | Specifies whether rbac roles are enable.                                                                                                                              |
