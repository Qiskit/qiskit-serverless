# Helm configuration

Main configuration to setup your k8s cluster and the services that this project uses. The helm configuration contains 4 charts: jupyter, middleware, operator and ray-cluster.

## Run

```shell
helm -n ray install quantum-serverless --create-namespace .
```

Install from specific values file
```shell
 helm -n ray install quantum-serverless -f <PATH_TO_VALUES_FILE> --create-namespace .
```

## Helm chart values

**Jupyter notebook**

| Name         | Description                                                    |
|--------------|----------------------------------------------------------------|
| jupyterEnable| Specify if helm will execute the jupyter configuration or not. |
| jupyterToken | Password for jupyter notebook.                                 |
| image        | Image setting for docker.                                      |
| service.port | Port number that service will be exposed externally.           |

**Middleware**

| Name                         | Description                                            |
|-------------------|-------------------------------------------------------------------|
| middlewareEnable  | Specify if helm will execute the middleware configuration or not. |
| image             | Image setting for docker.                                         |
| service.port      | Port number that service will be exposed externally.              |

**Ray cluster**

| Name                         | Description                                                                                                                                                                                                                                                                                                                                                            |
|------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| image                        | Image is Ray image to use for the head and workers of this Ray cluster. It's recommended to build custom dependencies for your workload into this image, taking one of the offical `rayproject/ray` images as base.                                                                                                                                                    |
| upscalingSpeed               | The autoscaler will scale up the cluster faster with higher upscaling speed. If the task requires adding more nodes then autoscaler will gradually scale up the cluster in chunks of upscaling_speed*currently_running_nodes. This number should be > 0.                                                                                                               |
| idleTimeoutMinutes           | If a node is idle for this many minutes, it will be removed.                                                                                                                                                                                                                                                                                                           |
| headPodType                  | headPodType is the podType used for the Ray head node (as configured below).                                                                                                                                                                                                                                                                                           |
| podTypes.<NAME>.cpu          | CPU is the number of CPUs used by this pod type                                                                                                                                                                                                                                                                                                                        |
| podTypes.<NAME>.memory       | memory is the memory used by this Pod type                                                                                                                                                                                                                                                                                                                             |
| podTypes.<NAME>.GPU          | GPU is the number of NVIDIA GPUs used by this pod type                                                                                                                                                                                                                                                                                                                 |
| podTypes.<NAME>.rayResources | rayResources is an optional str ing-int mapping signalling additional resources to Ray                                                                                                                                                                                                                                                                                 |
| podTypes.<NAME>.nodeSelector | Optionally, set a node selector for this podType: https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/#nodeselector                                                                                                                                                                                                                                |
| podTypes.<NAME>.tolerations  | tolerations for Ray pods of this podType (the head's podType in this case). ref: https://kubernetes.io/docs/concepts/configuration/taint-and-toleration/. Note that it is often not necessary to manually specify tolerations for GPU usage on managed platforms such as AKS, EKS, and GKE. ref: https://docs.ray.io/en/master/cluster/kubernetes-gpu.html             |
| operatorOnly                 | If true, will only set up the Operator with this release, without launching a Ray cluster.                                                                                                                                                                                                                                                                             |
| clusterOnly                  | If true, will only create a RayCluster resource with this release, without setting up the Operator.(Useful when launching multiple Ray clusters.)                                                                                                                                                                                                                      |
| namespacedOperator           | If true, the operator is scoped to the Release namespace and only manages RayClusters in that namespace. By default, the operator is cluster-scoped and runs in the default namespace.                                                                                                                                                                                 |
| operatorNamespace            | If using a cluster-scoped operator (namespacedOperator: false), set the namespace in which to launch the operator.                                                                                                                                                                                                                                                     |
| operatorImage                | The image used in the operator deployment. It is recommended to use one of the official `rayproject/ray` images for the operator. It is recommended to use the same Ray version in the operator as in the Ray clusters managed by the operator. In other words, the images specified under the fields `operatorImage` and `image` should carry matching Ray versions.  |
