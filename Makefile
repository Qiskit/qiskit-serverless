# =========
# Constants
# =========

version=latest
repository=icr.io/quantum-public
rayNodeImageName=$(repository)/qiskit-serverless/ray-node
gatewayImageName=$(repository)/qiskit-serverless/gateway
proxyImageName=$(repository)/qiskit-serverless/proxy

# =============
# Docker images
# =============

build-and-push: build-all push-all

build-all: build-ray-node build-gateway build-proxy
push-all: push-ray-node push-gateway push-proxy

build-ray-node:
	docker build -t $(rayNodeImageName):$(version) -f Dockerfile-ray-node .

build-gateway:
	docker build -t $(gatewayImageName):$(version) -f ./gateway/Dockerfile .

build-proxy:
	docker build -t $(proxyImageName):$(version) -f ./proxy/Dockerfile .

push-ray-node:
	docker push $(rayNodeImageName):$(version)

push-gateway:
	docker push $(gatewayImageName):$(version)

push-proxy:
	docker push $(proxyImageName):$(version)
