# Docker images

Docker images that the infrastructure requires to deploy. There are four main images:
- [Jupyter notebook](#ray-node-with-jupyter-notebook)
- [Ray](#custom-ray)
- [Repository server](#repository-server)
- [Gateway](#gateway)


## Custom ray

An image that contains our custom [ray](https://github.com/ray-project/ray) configuration.
It works for local development or to be used with [ray-cluster](https://docs.ray.io/en/latest/cluster/getting-started.html).

We provide support too for ARM chips too.


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
- Ray == 2.2.0
- Python == 3.9


## Ray node with Jupyter notebook

An image to be able to deploy a jupyter notebook in the infrastructure and make use of the project in an easy way without install anything locally.

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
- Python == 3.9


## Repository Server

An image of the repository server.

### Build
To build image just run from the root of the project:

```shell
make build-repository-server
```

or in case you want to customize as much as possible your build:

```shell
docker build -f ./infrastructure/docker/Dockerfile-repository-server -t <IMAGE_NAME> .
```

### Versions
- Python == 3.9


## Gateway

Image of the Gateway API.

### Build
To build image just run from the root of the project:

```shell
make build-gateway
```

or in case you want to customize as much as possible your build:

```shell
docker build -f ./infrastructure/docker/Dockerfile-gateway -t <IMAGE_NAME> .
```

### Versions
- Python == 3.9