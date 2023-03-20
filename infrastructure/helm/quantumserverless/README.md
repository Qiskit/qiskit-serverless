# Helm configuration

Main configuration to setup your k8s cluster and the services that this project uses. The helm configuration contains 5 charts: jupyter, kuberay-operator, ray-cluster, redis, and keycloak.

## Installation

```shell
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo add kuberay https://ray-project.github.io/kuberay-helm
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
```

```shell
helm dependency build
```
Update values.yaml file. Find and replace the following strings

- **CLIENTSECRET-CHANGEME**: string used as the secret for a OIDC protocol
- **APISERVERSECRET-CHANGEME**: string used as the secret for a OIDC protocol for apiserver
- **SECRET-CHANGEME**: string used as the secret for a OIDC protocol
- **HELM-RELEASE**: release name used in the helm install command
- **LOCAL-IP**: IP address that can be accessed from both outside of the cluster and inside of the cluster.  

**LOCAL-IP Example**

MacOS - ifconfig output (**192.168.4.23**)
```
en0: flags=8963<UP,BROADCAST,SMART,RUNNING,PROMISC,SIMPLEX,MULTICAST> mtu 1500
	options=6463<RXCSUM,TXCSUM,TSO4,TSO6,CHANNEL_IO,PARTIAL_CSUM,ZEROINVERT_CSUM>
	ether a4:83:e7:27:70:71
	inet6 fe80::8b4:58c9:11dd:e7e0%en0 prefixlen 64 secured scopeid 0x6
	inet 192.168.4.23 netmask 0xfffffc00 broadcast 192.168.7.255
	nd6 options=201<PERFORMNUD,DAD>
	media: autoselect
	status: active
```
Ubuntu - ifconfig output (**169.62.189.94**)
```
eth1: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
        inet 169.62.189.94  netmask 255.255.255.224  broadcast 169.62.189.95
        inet6 fe80::477:a9ff:fe0f:30c0  prefixlen 64  scopeid 0x20<link>
        ether 06:77:a9:0f:30:c0  txqueuelen 1000  (Ethernet)
        RX packets 41529956  bytes 5172595130 (5.1 GB)
        RX errors 0  dropped 0  overruns 0  frame 0
        TX packets 5373197  bytes 774842996 (774.8 MB)
        TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0
```
Kind - kubectl output (**172.18.0.2**)
```
# kubectl get node -o wide
NAME                 STATUS   ROLES           AGE    VERSION   INTERNAL-IP   EXTERNAL-IP   OS-IMAGE             KERNEL-VERSION      CONTAINER-RUNTIME
kind-control-plane   Ready    control-plane   5d6h   v1.25.3   172.18.0.2    <none>        Ubuntu 22.04.1 LTS   5.4.0-139-generic   containerd://1.6.9
```

Install from the default values file
```shell
helm -n ray install quantum-serverless --create-namespace .
```

Install from specific values file
```shell
 helm -n ray install quantum-serverless -f <PATH_TO_VALUES_FILE> --create-namespace .
```

(temporary) Patch the kuberay apiserver service

```shell
kubectl patch svc -n ray kuberay-apiserver-service --type json  --patch '[{"op" : "replace" ,"path" : "/spec/selector" ,"value" : {"app.kubernetes.io/component": "kuberay-apiserver"}}]'
```

(temporary) Patch the kuberay-apiserver deployment

```shell
./hack/apisesrver/patch.sh <LOCAL-IP>
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

**Keycloak**

- The initial user ID and password for both keycload console(adminUser/adminPassword) and Ray dashboard(keycloakUserID/keycloakPassword) can be changed in the values.yaml file. It is good to change them before apply the helm.
- Keycloak console can be accessed at http://LOCAL-IP:31059/.  Its initial user ID and password are "admin" and "passw0rd".
- Ray dashboard can be accessed at http://localhost/.  Its initial user ID and password are "user" and "passw0rd".

**Prometheus**

For our Prometheus dependency we are using the charts managed by the Prometheus community. To simplify the configuration we offered you with a straigh-forward initial parameters setup. But if you are interested in more complex configurations you have access to all the parameters in the chart's [values.yaml](https://github.com/prometheus-community/helm-charts/blob/main/charts/kube-prometheus-stack/values.yaml).

**loki**

- For our loki charts dependencies, we are using the single binary configuration created by Grafana project. To simplify the configuration we offered you with a straigh-forward initial parameters setup.
But if you are interested in more complex configurations, you have access to all the parameters documented [here](https://grafana.com/docs/loki/next/installation/helm/) and source code of the helm charts are
[here](https://github.com/grafana/loki/tree/main/production/helm/loki).

**promtail**

- For our promtail charts dependencies, we are using the default configuration created by Grafana project. To simplify the configuration we offered you with a straigh-forward initial parameters setup.
But if you are interested in more complex configurations, you have access to all the parameters documented [here](https://github.com/grafana/helm-charts/blob/main/charts/promtail/README.md).

## Usage

- Ray Api Server access needs the access token issued by the keycloak.  Here is the example to obtain the access token and send request to the Ray API Server

```
#!/bin/bash
API=$1
RESPONSE=$(curl --request POST \
  --url 'http://<LOCAL-IP>:31059/realms/quantumserverless/protocol/openid-connect/token' \
  --header 'content-type: application/x-www-form-urlencoded' \
  --data grant_type=client_credentials \
  --data client_id=rayapiserver \
  --data client_secret=APISERVERSECRET-CHANGEME \
  --data audience=rayapiserver | jq .access_token)
TOKEN=${RESPONSE//'"'/}

curl --request GET -k --proxy http://<LOCAL-IP>:30634/ \
--header "authorization: Bearer $TOKEN" \
--header 'content-type: application/json' \
--url "http://kuberay-apiserver-service:8888/$API"
```
