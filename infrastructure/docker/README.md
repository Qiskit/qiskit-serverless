# Docker images

Docker images that the infrastructure requires to deploy. There are two main images:
- [Jupyter notebook](#ray-node-with-jupyter-notebook)
- [Ray](#ray-node-with-qiskit)


## Ray node with Qiskit

An image that contains the ray library to be used in the infrastructure.

### Build
To build image just run from the root of the project:
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
docker build -f ./infrastructure/docker/Dockerfile-notebook -t <IMAGE_NAME> .
```

### Versions
- Python == 3.7
