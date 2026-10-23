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

# --target selector-gpu, NOT selector, even though this is the heavier image.
# fleet-node is the name FLEETS_DEFAULT_IMAGE and the chart's ce.fleetsDefaultImage
# resolve to, so it is what the gateway deploys for every imageless Fleets job --
# including one on a GPU compute profile. Before the CPU/GPU split this target was
# a bare build, which resolved to the only shipped stage, and that stage carried
# the CUDA wheels; so fleet-node has always had CUDA and must keep it until the
# gateway can choose per compute profile. Building the CPU stage here would
# publish a CUDA-free image under the same name and tag, and the failure would be
# silent: gpu4pyscf's import fails, the chemistry function falls back to CPU, and
# the job still succeeds (see the note in
# requirements-dynamic-dependencies-gpu.txt). Nothing downstream would flag it.
#
# So the split does not yet change which image a job gets. What it adds is
# fleet-selector (CPU) and fleet-selector-gpu published alongside, ready for the
# gateway to pick between them; at that point this target becomes the CPU stage
# and FLEETS_DEFAULT_IMAGE moves with it.
#
# No fleet-node:latest tag here any more. That tag is what the fleets
# integration-test worker builds FROM, and the test wants the CPU runtime: it has
# no GPU to exercise, the CUDA wheels would add 6.5 GB to a local run, and
# gpu4pyscf-cuda12x publishes no aarch64 wheel so this target cannot be built on
# Apple Silicon at all. Use build-fleet-node-local for that tag.
build-fleet-node:
	docker build --target selector-gpu -t $(fleetNodeImageName):$(version) -f ./docker-images/fleet-node/Dockerfile .

# The fleets integration-test base, tagged the way the test harness expects:
# tests/fleets/fleet-worker/Dockerfile is FROM ${BASE_IMAGE:-fleet-node:latest},
# and `compose up --build` does not build a FROM-referenced base, so this has to
# run first. The CPU stage on purpose -- see the note on build-fleet-node above.
# Local only: it publishes nothing, which is why it carries no registry tag.
build-fleet-node-local:
	docker build --target selector -t fleet-node:latest -f ./docker-images/fleet-node/Dockerfile .

# The CPU Fleets runtime under its own name. Unlike build-fleet-node, it has no
# CUDA wheels.
build-fleet-selector:
	docker build --target selector -t $(fleetSelectorImageName):$(version) -t fleet-selector:latest -f ./docker-images/fleet-node/Dockerfile .

# The CUDA Fleets runtime: the same workload stack as fleet-selector plus the
# CUDA wheels, for jobs on a GPU compute profile. Published separately so a CPU
# job does not pull the 6.5 GB of wheels it never imports — Fleets pulls the image
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
