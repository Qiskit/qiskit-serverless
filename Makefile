# =============
# Constants
# =============

version=0.0.1
repository=qiskit

notebookImageName=$(repository)/quantum-serverless-notebook
rayNodeImageName=$(repository)/quantum-serverless-ray-node
managerImageName=$(repository)/quantum-serverless-manager

# =============
# Docker images
# =============

build-and-push: build-all push-all

build-all: build-manager build-notebook build-ray-node
push-all: push-manager push-notebook push-ray-node

build-manager:
	docker build -t $(managerImageName):$(version) -f ./manager/Dockerfile .

build-notebook:
	docker build -t $(notebookImageName):$(version) -f ./infrastructure/docker/Dockerfile-notebook .

build-ray-node:
	docker build -t $(rayNodeImageName):$(version) -f ./infrastructure/docker/Dockerfile-ray-qiskit .

push-manager:
	docker push $(managerImageName):$(version)

push-notebook:
	docker push $(notebookImageName):$(version)

push-ray-node:
	docker push $(rayNodeImageName):$(version)
