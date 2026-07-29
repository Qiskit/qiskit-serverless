# =========
# Constants
# =========

version=latest
repository=icr.io/quantum-public
rayNodeImageName=$(repository)/qiskit-serverless/ray-node
fleetNodeImageName=$(repository)/qiskit-serverless/fleet-node
gatewayImageName=$(repository)/qiskit-serverless/gateway

# =============
# Docker images
# =============

build-and-push: build-all push-all

build-all: build-ray-node build-fleet-node build-gateway
push-all: push-ray-node push-fleet-node push-gateway

build-ray-node:
	docker build -t $(rayNodeImageName):$(version) -f ./ray-node/Dockerfile .

# Also tag it fleet-node:latest so the fleets integration-test worker
# (tests/fleets/fleet-worker/Dockerfile, FROM ${BASE_IMAGE:-fleet-node:latest})
# can build on it locally without needing the full registry path.
build-fleet-node:
	docker build -t $(fleetNodeImageName):$(version) -t fleet-node:latest -f ./fleet-node/Dockerfile .

build-gateway:
	docker build -t $(gatewayImageName):$(version) -f ./gateway/Dockerfile .

push-ray-node:
	docker push $(rayNodeImageName):$(version)

push-fleet-node:
	docker push $(fleetNodeImageName):$(version)

push-gateway:
	docker push $(gatewayImageName):$(version)
