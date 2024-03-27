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

rayNodeImageName=$(repository)/quantum-serverless-ray-node
gatewayImageName=$(repository)/quantum-serverless-gateway
proxyImageName=$(repository)/quantum-serverless-proxy

# =============
# Docker images
# =============

build-and-push: build-all push-all

build-all: build-ray-node build-gateway build-proxy
push-all: push-ray-node push-gateway push-proxy

build-ray-node:
	docker build -t $(rayNodeImageName):$(version) --build-arg TARGETARCH=$(arch) -f Dockerfile-ray-node .
	docker build -t $(rayNodeImageName):$(version)-py310 --build-arg TARGETARCH=$(arch) --build-arg IMAGE_PY_VERSION=py310 -f Dockerfile-ray-node .
	docker build -t $(rayNodeImageName):$(version)-py39  --build-arg TARGETARCH=$(arch) --build-arg IMAGE_PY_VERSION=py39  -f Dockerfile-ray-node .

build-gateway:
	docker build -t $(gatewayImageName):$(version) -f ./gateway/Dockerfile .

build-proxy:
	docker build -t $(proxyImageName):$(version) -f ./gateway/proxy/Dockerfile .

push-ray-node:
	docker push $(rayNodeImageName):$(version)

push-gateway:
	docker push $(gatewayImageName):$(version)

push-proxy:
	docker push $(proxyImageName):$(version)
