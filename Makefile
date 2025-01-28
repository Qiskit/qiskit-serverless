# =========
# Constants
# =========

version=latest
repository=icr.io/quantum-public
rayNodeImageName=$(repository)/qiskit-serverless/ray-node
gatewayImageName=$(repository)/qiskit-serverless/gateway

# =============
# Docker images
# =============

build-and-push: build-all push-all

build-all: build-ray-node build-gateway
push-all: push-ray-node push-gateway

build-ray-node:
	docker build -t $(rayNodeImageName):$(version) -f Dockerfile-ray-node .

build-gateway:
	docker build -t $(gatewayImageName):$(version) -f ./gateway/Dockerfile .

push-ray-node:
	docker push $(rayNodeImageName):$(version)

push-gateway:
	docker push $(gatewayImageName):$(version)
