#!/usr/bin/env make

-include ./ci/helpers.mk

# =========
# Constants
# =========

DEBUG_MODE                ?= true
DOCKER_FILE_GATEWAY       ?= ./gateway/Dockerfile
DOCKER_FILE_NOTEBOOK      ?= ./Dockerfile-notebook
DOCKER_FILE_RAY_NODE      ?= ./Dockerfile-ray-node
DOCKER_FILE_SELECTOR  	  ?= ./tools/Dockerfile

DOCKER_REGISTRY           			:= icr.io
DOCKER_REGISTRY_NAMESPACE 			:= quantum-public
DOCKER_PRIVATE_REGISTRY_NAMESPACE 	:= qc-middleware-prod

TARGET_SERVICE			  ?= qiskit-serverless
ENVIRONMENT               ?= development
PROJECT_VERSION			  ?= latest

DOCKER_IMAGE_GATEWAY      := $(DOCKER_REGISTRY)/$(DOCKER_REGISTRY_NAMESPACE)/qiskit-serverless/gateway
DOCKER_IMAGE_NOTEBOOK     := $(DOCKER_REGISTRY)/$(DOCKER_REGISTRY_NAMESPACE)/qiskit-serverless/notebook
DOCKER_IMAGE_RAY_NODE     := $(DOCKER_REGISTRY)/$(DOCKER_REGISTRY_NAMESPACE)/qiskit-serverless/ray-node
DOCKER_IMAGE_SELECTOR 	  := $(DOCKER_REGISTRY)/$(DOCKER_PRIVATE_REGISTRY_NAMESPACE)/qiskit-serverless/selector
DOCKER_IMAGE_SELECTOR_TAG := 0.14.1

# =========
# CI Commands
# =========

.PHONY: docker/lint-gateway
docker/lint-gateway: DOCKER_FILE 			:= $(DOCKER_FILE_GATEWAY)
docker/lint-gateway: docker/lint

.PHONY: docker/lint-ray
docker/lint-ray: DOCKER_FILE 				:= $(DOCKER_FILE_RAY_NODE)
docker/lint-ray: docker/lint

.PHONY: docker/lint-selector
docker/lint-selector: DOCKER_FILE 		:= $(DOCKER_FILE_SELECTOR)
docker/lint-selector: docker/lint

.PHONY: docker/sast-gateway
docker/sast-gateway: DOCKER_FILE 			:= $(DOCKER_FILE_GATEWAY)
docker/sast-gateway: docker/sast

.PHONY: docker/sast-ray
docker/sast-ray: DOCKER_FILE 				:= $(DOCKER_FILE_RAY_NODE)
docker/sast-ray: docker/sast

.PHONY: docker/sast-selector
docker/sast-selector: DOCKER_FILE 		:= $(DOCKER_FILE_SELECTOR)
docker/sast-selector: docker/sast

.PHONY: docker/vscan-gateway
docker/vscan-gateway: DOCKER_FILE 			:= $(DOCKER_FILE_GATEWAY)
docker/vscan-gateway: DOCKER_IMAGE 			:= $(DOCKER_IMAGE_GATEWAY)
docker/vscan-gateway: IMAGE_TAG 			:= $(PROJECT_VERSION)
docker/vscan-gateway: PY_VERSION 			:= "3.9"
docker/vscan-gateway: docker/vscan

.PHONY: docker/vscan-ray-py39
docker/vscan-ray-py39: DOCKER_FILE 			:= $(DOCKER_FILE_RAY_NODE)
docker/vscan-ray-py39: DOCKER_IMAGE 		:= $(DOCKER_IMAGE_RAY_NODE)
docker/vscan-ray-py39: IMAGE_TAG 			:= $(PROJECT_VERSION)-py39
docker/vscan-ray-py39: PY_VERSION 			:= "py39"
docker/vscan-ray-py39: docker/vscan

.PHONY: docker/vscan-ray-py310
docker/vscan-ray-py310: DOCKER_FILE 		:= $(DOCKER_FILE_RAY_NODE)
docker/vscan-ray-py310: DOCKER_IMAGE 		:= $(DOCKER_IMAGE_RAY_NODE)
docker/vscan-ray-py310: IMAGE_TAG 			:= $(PROJECT_VERSION)-py310
docker/vscan-ray-py310: PY_VERSION 			:= "py310"
docker/vscan-ray-py310: docker/vscan

.PHONY: docker/vscan-selector
docker/vscan-selector: DOCKER_FILE 			:= $(DOCKER_FILE_SELECTOR)
docker/vscan-selector: DOCKER_IMAGE 		:= $(DOCKER_IMAGE_SELECTOR)
docker/vscan-selector: IMAGE_TAG 			:= $(PROJECT_VERSION)
docker/vscan-selector: PY_VERSION 			:= "3.10"
docker/vscan-selector: docker/vscan

.PHONY: docker/release-selector
docker/release-selector: DOCKER_FILE 		:= $(DOCKER_FILE_SELECTOR)
docker/release-selector: DOCKER_IMAGE 		:= $(DOCKER_IMAGE_SELECTOR)
docker/release-selector: IMAGE_TAG 			:= $(DOCKER_IMAGE_SELECTOR_TAG)
docker/release-selector: PY_VERSION 		:= "3.10"
docker/release-selector: docker/release
