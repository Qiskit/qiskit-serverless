# =========
# Constants
# =========

version=latest
repository=icr.io/quantum-public
rayNodeImageName=$(repository)/qiskit-serverless/ray-node
fleetNodeImageName=$(repository)/qiskit-serverless/fleet-node
fleetSelectorImageName=$(repository)/qiskit-serverless/fleet-selector
fleetSelectorGpuImageName=$(repository)/qiskit-serverless/fleet-selector-gpu
gatewayImageName=$(repository)/qiskit-serverless/gateway

# =============
# Docker images
# =============

build-and-push: build-all push-all

build-all: build-ray-node build-fleet-node build-fleet-selector build-fleet-selector-gpu build-gateway
push-all: push-ray-node push-fleet-node push-fleet-selector push-fleet-selector-gpu push-gateway

build-ray-node:
	docker build -t $(rayNodeImageName):$(version) -f ./docker-images/ray-node/Dockerfile .

# selector-gpu, NOT selector: fleet-node is what FLEETS_DEFAULT_IMAGE resolves to,
# so it serves every imageless job including those on a GPU compute profile, and
# the gateway cannot choose per profile yet. Building the CPU stage here would
# strip CUDA from GPU jobs silently. specs/FLEETS_IMAGES.md §2.
#
# No fleet-node:latest tag: that is the fleets-test base, which wants the CPU
# stage. Use build-fleet-node-local.
build-fleet-node:
	docker build --target selector-gpu -t $(fleetNodeImageName):$(version) -f ./docker-images/fleet-node/Dockerfile .

# The fleets integration-test base: tests/fleets/fleet-worker/Dockerfile is FROM
# ${BASE_IMAGE:-fleet-node:latest} and `compose up --build` will not build a
# FROM-referenced base, so run this first. Local only, hence no registry tag.
build-fleet-node-local:
	docker build --target selector -t fleet-node:latest -f ./docker-images/fleet-node/Dockerfile .

# The CPU Fleets runtime under its own name. Unlike build-fleet-node, it has no
# CUDA wheels.
build-fleet-selector:
	docker build --target selector -t $(fleetSelectorImageName):$(version) -t fleet-selector:latest -f ./docker-images/fleet-node/Dockerfile .

# The CUDA Fleets runtime: fleet-selector plus the CUDA wheels, published
# separately so a CPU job does not pull the 6.5 GB it never imports. x86_64 only
# — gpu4pyscf-cuda12x has no aarch64 wheel, so this needs --platform emulation on
# Apple Silicon.
build-fleet-selector-gpu:
	docker build --target selector-gpu -t $(fleetSelectorGpuImageName):$(version) -t fleet-selector-gpu:latest -f ./docker-images/fleet-node/Dockerfile .

build-gateway:
	docker build -t $(gatewayImageName):$(version) -f ./gateway/Dockerfile .

push-ray-node:
	docker push $(rayNodeImageName):$(version)

push-fleet-node:
	docker push $(fleetNodeImageName):$(version)

push-fleet-selector:
	docker push $(fleetSelectorImageName):$(version)

push-fleet-selector-gpu:
	docker push $(fleetSelectorGpuImageName):$(version)

push-gateway:
	docker push $(gatewayImageName):$(version)
