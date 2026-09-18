# =========
# Constants
# =========

version=latest
repository=icr.io/quantum-public
rayNodeImageName=$(repository)/qiskit-serverless/ray-node
fleetNodeImageName=$(repository)/qiskit-serverless/fleet-node
fleetSelectorImageName=$(repository)/qiskit-serverless/fleet-selector
gatewayImageName=$(repository)/qiskit-serverless/gateway

# =============
# Docker images
# =============

build-and-push: build-all push-all

build-all: build-ray-node build-fleet-node build-fleet-selector build-gateway
push-all: push-ray-node push-fleet-node push-fleet-selector push-gateway

build-ray-node:
	docker build -t $(rayNodeImageName):$(version) -f ./docker-images/ray-node/Dockerfile .

# Also tag it fleet-node:latest so the fleets integration-test worker
# (tests/fleets/fleet-worker/Dockerfile, FROM ${BASE_IMAGE:-fleet-node:latest})
# can build on it locally without needing the full registry path.
build-fleet-node:
	docker build -t $(fleetNodeImageName):$(version) -t fleet-node:latest -f ./docker-images/fleet-node/Dockerfile .

# The selector stage on its own, so the full Fleets runtime can be built and
# published under its own name. In this repo selector is the last stage of
# docker-images/fleet-node/Dockerfile, so this currently produces the same image
# as build-fleet-node — kept as a separate target and tag on purpose: sharing
# them would make the result depend on which target ran last.
build-fleet-selector:
	docker build --target selector -t $(fleetSelectorImageName):$(version) -t fleet-selector:latest -f ./docker-images/fleet-node/Dockerfile .

build-gateway:
	docker build -t $(gatewayImageName):$(version) -f ./gateway/Dockerfile .

push-ray-node:
	docker push $(rayNodeImageName):$(version)

push-fleet-node:
	docker push $(fleetNodeImageName):$(version)

push-fleet-selector:
	docker push $(fleetSelectorImageName):$(version)

push-gateway:
	docker push $(gatewayImageName):$(version)
