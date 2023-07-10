# Helm configuration

Main configuration to setup an observability stack for your k8s cluster. The helm configuration contains the details for setting up Grafana, Prometheus, and Loki.

## Installation

```shell
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
```

```shell
helm dependency build
```
Update values.yaml file. Find and replace the following strings

- **GRAFANASECRET-CHANGEME**: string used as the secret for a OIDC protocol for Grafana

Install from the default values file
```shell
helm -n quantum-serverless install qs-observability .
```

Install from specific values file
```shell
 helm -n quantum-serverless install qs-observability -f <PATH_TO_VALUES_FILE>  .
```

## Helm chart versions

The Quantum Serverless Chart has several internal and external dependencies. If you are interested to know what versions the project is using you can check them in the [Chart.lock file](./Chart.lock).

## Helm chart values

**Prometheus**

For our Prometheus dependency we are using the charts managed by the Prometheus community. To simplify the configuration we offered you with a straigh-forward initial parameters setup. But if you are interested in more complex configurations you have access to all the parameters in the chart's [values.yaml](https://github.com/prometheus-community/helm-charts/blob/main/charts/kube-prometheus-stack/values.yaml).

**loki**

- For our loki charts dependencies, we are using the single binary configuration created by Grafana project. To simplify the configuration we offered you with a straigh-forward initial parameters setup.
But if you are interested in more complex configurations, you have access to all the parameters documented [here](https://grafana.com/docs/loki/next/installation/helm/) and source code of the helm charts are
[here](https://github.com/grafana/loki/tree/main/production/helm/loki).

**Grafana**

- For our Grafana charts dependencies, we are configuring authentication by Keycloak and providing some predefined dashboards.
If you are interested in more complex configurations, you have access to all the parameters documented [here](https://github.com/grafana/helm-charts/tree/main/charts/grafana).
- The initial user ID and password for Grafana console(keycloakAdminID/keycloakAdminPassword) can be changed in the values.yaml file. It is good to change them before apply the helm.
- Grafana console can be accessed at http://LOCAL-IP:32294/.  Its initial user ID and password are "admin" and "passw0rd".

**promtail**

- For our promtail charts dependencies, we are using the default configuration created by Grafana project. To simplify the configuration we offered you with a straigh-forward initial parameters setup.
But if you are interested in more complex configurations, you have access to all the parameters documented [here](https://github.com/grafana/helm-charts/blob/main/charts/promtail/README.md).
