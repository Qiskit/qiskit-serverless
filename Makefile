# =========
# Constants
# =========

version=0.0.5
repository=qiskit

notebookImageName=$(repository)/quantum-serverless-notebook
rayNodeImageName=$(repository)/quantum-serverless-ray-node
managerImageName=$(repository)/quantum-serverless-manager
repositoryServerImageName=$(repository)/quantum-repository-server

# =============
# Docker images
# =============

build-and-push: build-all push-all

build-all: build-manager build-notebook build-ray-node build-repository-server
push-all: push-manager push-notebook push-ray-node push-repository-server

build-manager:
	docker build -t $(managerImageName):$(version) -f ./manager/Dockerfile .

build-notebook:
	docker build -t $(notebookImageName):$(version) -f ./infrastructure/docker/Dockerfile-notebook .

build-ray-node:
	docker build -t $(rayNodeImageName):$(version) -f ./infrastructure/docker/Dockerfile-ray-qiskit .

build-repository-server:
	docker build -t $(repositoryServerImageName):$(version) -f ./infrastructure/docker/Dockerfile-repository-server .

push-manager:
	docker push $(managerImageName):$(version)

push-notebook:
	docker push $(notebookImageName):$(version)

push-ray-node:
	docker push $(rayNodeImageName):$(version)

push-repository-server:
	docker push $(repositoryServerImageName):$(version)
