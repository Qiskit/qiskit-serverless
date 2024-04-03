#!/usr/bin/env make

-include ./ci/internal-makefile.mk

# =========
# Constants
# =========

version=latest
repository=icr.io/quantum-public
ifeq ($(shell uname -p), arm)
	arch="arm64"
else
	arch="amd64"
endif

notebookImageName=$(repository)/quantum-serverless-notebook
rayNodeImageName=$(repository)/quantum-serverless-ray-node
gatewayImageName=$(repository)/quantum-serverless-gateway

# =============
# Docker images
# =============

build-and-push: build-all push-all

build-all: build-notebook build-ray-node build-gateway
push-all: push-notebook push-ray-node push-gateway

build-notebook:
	docker build -t $(notebookImageName):$(version) -f Dockerfile-notebook .

build-ray-node:
	docker build -t $(rayNodeImageName):$(version) --build-arg TARGETARCH=$(arch) -f Dockerfile-ray-node .
	docker build -t $(rayNodeImageName):$(version)-py310 --build-arg TARGETARCH=$(arch) --build-arg IMAGE_PY_VERSION=py310 -f Dockerfile-ray-node .
	docker build -t $(rayNodeImageName):$(version)-py39  --build-arg TARGETARCH=$(arch) --build-arg IMAGE_PY_VERSION=py39  -f Dockerfile-ray-node .
	docker build -t $(rayNodeImageName):$(version)-py38  --build-arg TARGETARCH=$(arch) --build-arg IMAGE_PY_VERSION=py38  -f Dockerfile-ray-node .

build-gateway:
	docker build -t $(gatewayImageName):$(version) -f ./gateway/Dockerfile .

push-notebook:
	docker push $(notebookImageName):$(version)

push-ray-node:
	docker push $(rayNodeImageName):$(version)

push-gateway:
	docker push $(gatewayImageName):$(version)
