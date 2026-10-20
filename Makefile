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

# Also tag it fleet-node:latest so the fleets integration-test worker
# (tests/fleets/fleet-worker/Dockerfile, FROM ${BASE_IMAGE:-fleet-node:latest})
# can build on it locally without needing the full registry path.
#
# --target selector is required, not decoration: selector-gpu is the last stage
# of docker-images/fleet-node/Dockerfile, so a bare build here would produce the
# ~4.6 GB CUDA image instead of the CPU runtime.
build-fleet-node:
	docker build --target selector -t $(fleetNodeImageName):$(version) -t fleet-node:latest -f ./docker-images/fleet-node/Dockerfile .

# The CPU Fleets runtime published under its own name. Same stage as
# build-fleet-node above, so the two produce the same image — kept as a separate
# target and tag on purpose: sharing them would make the result depend on which
# target ran last.
build-fleet-selector:
	docker build --target selector -t $(fleetSelectorImageName):$(version) -t fleet-selector:latest -f ./docker-images/fleet-node/Dockerfile .

# The CUDA Fleets runtime: the same workload stack as fleet-selector plus the
# CUDA wheels, for jobs on a GPU compute profile. Published separately so a CPU
# job does not pull ~2.5 GB of wheels it never imports — Fleets pulls the image
# once per job. x86_64 only: gpu4pyscf-cuda12x publishes no aarch64 wheel, so
# this target cannot be built on Apple Silicon without --platform emulation.
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
