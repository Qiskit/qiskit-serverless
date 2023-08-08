# Helm configuration

Main configuration to setup your k8s cluster and the services that this project uses. The helm configuration contains 5 charts: jupyter, kuberay-operator, ray-cluster, redis, and keycloak.

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

**Redis & Nginx Ingress controller**

For our Redis and Nginx Ingress controller dependencies we are using the configuration created by Bitnami. To simplify the configuration we offered you with a straigh-forward initial parameters setup. 
But if you are interested in more complex configurations you have access to all the parameters that Bitnami added in the chart specified in their READMEs:
* [Redis README](https://artifacthub.io/packages/helm/bitnami/redis).
* [Nginx Ingress controller's README](https://artifacthub.io/packages/helm/bitnami/nginx-ingress-controller)

For our keycloak dependencies we are using the configuration created by Bitnami. To simplify the configuration we offered you with a straigh-forward initial parameters setup. 
But if you are interested in more complex configurations you have access to all the parameters that Bitnami added in the chart specified in their READMEs:
* [keycloak README](https://artifacthub.io/packages/helm/bitnami/keycloak)

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

**Ray cluster, Kuberay operator, and Kuberay api server**

For our Ray Charts dependencies we are using the configuration created by the Ray Project. To simplify the configuration we offered you with a straigh-forward initial parameters setup. But if you are interested in more complex configurations you have access to their Helm project [in GitHub](https://github.com/ray-project/kuberay-helm) to analyze the different variables:

- For Kuberay Operator you can read their [values.yaml](https://github.com/ray-project/kuberay-helm/blob/main/helm-chart/kuberay-operator/values.yaml).

- For Ray Cluster they provide you with a commented initial setup in their [values.yaml](https://github.com/ray-project/kuberay-helm/blob/main/helm-chart/ray-cluster/values.yaml).

- For Ray Api Server you can read their [values.yaml](https://github.com/ray-project/kuberay-helm/blob/main/helm-chart/kuberay-apiserver/values.yaml).

TLS is enabled for the gRPC communication among Ray components.  It uses a self-signed certificate by derault.  It can optionally use certificates signed by the cert manager in the environment that has the cert manager installed. The option is `gateway.useCertManager: ture`

**Keycloak**

- The initial user ID and password for both keycload console(adminUser/adminPassword) and Ray dashboard(keycloakUserID/keycloakPassword) can be changed in the values.yaml file. It is good to change them before apply the helm.
- Keycloak console can be accessed at http://LOCAL-IP:31059/.  Its initial user ID and password are "admin" and "passw0rd".
- Ray dashboard can be accessed at http://localhost/.  Its initial user ID and password are "user" and "passw0rd".
