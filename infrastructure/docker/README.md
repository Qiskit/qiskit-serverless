# Docker images

Docker images that the infrastructure requires to deploy. There are two main images:
- [Jupyter notebook](#ray-node-with-jupyter-notebook)
- [Ray](#custom-ray-cluster)


## Custom ray-cluster

An image that contains our custom ray-cluster configuration.

### Build
To build image just run from the root of the project:

```shell
make build-ray-node
```

or in case you want to customize as much as possible your build:

```shell
docker build -f ./infrastructure/docker/Dockerfile-ray-qiskit -t <IMAGE_NAME> .
```

### Versions
- Ray == 2.0.0
- Python == 3.7


## Ray node with Jupyter notebook

An image to be able to deploy a jupyter notebook in the infrastructure and make use of the project in a easy way without install anything locally.

### Build
To build image just run from the root of the project:

```shell
make build-notebook
```

or in case you want to customize as much as possible your build:

```shell
docker build -f ./infrastructure/docker/Dockerfile-notebook -t <IMAGE_NAME> .
```

### Versions
- Python == 3.7
