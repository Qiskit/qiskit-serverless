[![Stability](https://img.shields.io/badge/stability-alpha-f4d03f.svg)](https://github.com/Qiskit-Extensions/quantum-serverless/releases)
[![Manager verify process](https://github.com/Qiskit-Extensions/quantum-serverless/actions/workflows/manager-verify.yaml/badge.svg)](https://github.com/Qiskit-Extensions/quantum-serverless/actions/workflows/manager-verify.yaml)
[![License](https://img.shields.io/github/license/qiskit-community/quantum-prototype-template?label=License)](https://github.com/qiskit-community/quantum-prototype-template/blob/main/LICENSE.txt)

# Quantum Serverless manager

Manager middleware part of quantum serverless project. 
Restful application for auto-discovery of clusters within kubernetes deployment.

> NOTE: manager only works in kubernetes namespace and exposes internal kubernetes dns records of cluster services.
> QuantumServerless client uses this service (if available) to set available providers.

### Table of Contents

1. [Installation](#installation)
2. [Usage](#usage)

----------------------------------------------------------------------------------------------------

### Installation

Installed as a part of [helm](../infrastructure/helm/quantumserverless) chart.

To build docker image run from root folder of this repo

```shell
docker build -f manager/Dockerfile -t <REPOSITORY>:<TAG> .
```

or

```shell
make build-manager
```

----------------------------------------------------------------------------------------------------


### Usage

Manager exposes endpoints to access information about available clusters.

GET: `/quantum-serverless-middleware/cluster/`

Response body:
```json
[
  {"name":  "<CLUSTER_NAME>"},
  {"name":  "<CLUSTER_NAME_2>"}
]
```

GET: `/quantum-serverless-middleware/cluster/<CLUSTER_NAME>`

Response body:
```json
{
  "name": "<CLUSTER_NAME>",
  "host": "<CLUSTER_SERVICE_DNS_ADDRESS>",
  "port": 10001
}
```
