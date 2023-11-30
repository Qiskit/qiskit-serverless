# Helm configuration

Main configuration to setup your k8s cluster and the services that this project uses. The helm configuration contains 3 main charts: gateway/scheduler, jupyter and kuberay-operator.

## Installation

```shell
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo add kuberay https://ray-project.github.io/kuberay-helm
```

```shell
helm dependency build
```
Update values.yaml file. Find and replace the following strings

- **GATEWAY-CHANGEME**: string used as the secret for a OIDC protocol

Install from the default values file
```shell
helm -n quantum-serverless install quantum-serverless --create-namespace .
```

Install from specific values file
```shell
 helm -n quantum-serverless install quantum-serverless -f <PATH_TO_VALUES_FILE> --create-namespace .
```

## Helm chart versions

The Quantum Serverless Chart has several internal and external dependencies. If you are interested to know what versions the project is using you can check them in the [Chart.lock file](./Chart.lock).

## Helm chart values

**Nginx Ingress controller**

For our Nginx Ingress controller dependency we are using the configuration created by Bitnami. To simplify the configuration we offered you with a straigh-forward initial parameters setup. 
But if you are interested in more complex configurations you have access to all the parameters that Bitnami added in the chart specified in their READMEs:
* [Nginx Ingress controller's README](https://artifacthub.io/packages/helm/bitnami/nginx-ingress-controller)

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

**Kuberay operator**

For our KubeRay Chart dependency we are using the configuration created by the Ray Project. To simplify the configuration we offered you with a straigh-forward initial parameters setup. But if you are interested in more complex configurations you have access to their Helm project [in GitHub](https://github.com/ray-project/kuberay-helm) to analyze the different variables:

- For Kuberay Operator you can read their [values.yaml](https://github.com/ray-project/kuberay-helm/blob/main/helm-chart/kuberay-operator/values.yaml).

TLS is enabled for the gRPC communication among Ray components.  It uses a self-signed certificate by default.  It can optionally use certificates signed by the cert manager in the environment that has the cert manager installed. The option is `gateway.useCertManager: true`.


**Gateway & Scheduler**

Gateway is the API that we offer to manage Qiskit Patterns. Scheduler is the part of the API that manages Qiskit Pattern executions and Ray Cluster creation for the user. Gateway, Scheduler and Ray Cluster configurations can be modified through helm to adapt Quantum Serverless behaviour to user's needs. Values that you can modify for it are:

| Name                                      | Description                                                                                                                                                                                   |
|-------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| application.debug                         | enable / disable debug mode using 0, 1                                                                                                                                                        |
| application.rayHost                       | KubeRay head service domain in case it changes from default                                                                                                                                   |
| application.auth.mechanism                | `mock_token` use a default token to authenticate for tests and local development, `custom_token` lets you to configure an authentication process against a 3rd party service using a token    |
| application.auth.token.url                | 3rd party service domain to login with the token                                                                                                                                              |
| application.auth.token.verificationUrl    | 3rd party service domain to verify that the token is yours                                                                                                                                    |
| application.auth.token.verificationField  | set of fields that will verify the access of the user to the service                                                                                                                          |
| application.superuser.enable              | enable / disable superuser creation in the system                                                                                                                                             |
| application.ray.nodeImage                 | docker image to create the ray cluster for the user                                                                                                                                           |
| application.ray.cpu                       | number of cpus available per ray node                                                                                                                                                         |
| application.ray.memory                    | gigabytes of available memory per ray node                                                                                                                                                    |
| application.limits.maxJobsPerUser         | maximum numbers of jobs that a user can have running at the same time                                                                                                                         |
| application.limits.maxComputeResources    | maximum numbers of jobs that the cluster can manage at the same time                                                                                                                          |
| secrets.secretKey.create                  | enable / disable gateway's secretKey creation                                                                                                                                                 |
| secrets.secretKey.*                       | `name` and `key` let you to specify the secret and `value` the value for the secret                                                                                                           |
| secrets.servicePsql.create                | Port number that service will be exposed externally                                                                                                                                           |
| secrets.servicePsql.*                     | `name` and `key` let you to specify the secret and `value` the value for the secret                                                                                                           |
| secrets.superuser.create                  | Port number that service will be exposed externally                                                                                                                                           |
| secrets.superuser.*                       | `name` and `key` let you to specify the secret and `value` the value for the secret                                                                                                           |
