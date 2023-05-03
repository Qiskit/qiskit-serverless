# =========
# Constants
# =========

version=0.0.7
repository=qiskit

notebookImageName=$(repository)/quantum-serverless-notebook
rayNodeImageName=$(repository)/quantum-serverless-ray-node
gatewayImageName=$(repository)/quantum-serverless-gateway
repositoryServerImageName=$(repository)/quantum-repository-server

# =============
# Docker images
# =============

build-and-push: build-all push-all

build-all: build-notebook build-ray-node build-gateway build-repository-server
push-all: push-notebook push-ray-node push-gateway push-repository-server

build-notebook:
	docker build -t $(notebookImageName):$(version) -f ./infrastructure/docker/Dockerfile-notebook --platform=linux/amd64 .

build-ray-node:
	docker build -t $(rayNodeImageName):$(version) -f ./infrastructure/docker/Dockerfile-ray-qiskit --platform=linux/amd64 .

build-gateway:
	docker build -t $(gatewayImageName):$(version) -f ./infrastructure/docker/Dockerfile-gateway --platform=linux/amd64 .

build-repository-server:
	docker build -t $(repositoryServerImageName):$(version) -f ./infrastructure/docker/Dockerfile-repository-server --platform=linux/amd64 .

push-notebook:
	docker push $(notebookImageName):$(version)

push-ray-node:
	docker push $(rayNodeImageName):$(version)

push-gateway:
	docker push $(gatewayImageName):$(version)

push-repository-server:
	docker push $(repositoryServerImageName):$(version)
