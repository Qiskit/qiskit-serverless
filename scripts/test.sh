#!/usr/bin/env bash

SCRIPT_NAME=$(basename $0)
echo "Running ${SCRIPT_NAME}"
echo "###"

version=latest
repository=icr.io/quantum-public
arch="amd64"

rayNodeImageName=$repository/qiskit-serverless-ray-node
gatewayImageName=$repository/qiskit-serverless-gateway
proxyImageName=$repository/qiskit-serverless-proxy

docker build -t $rayNodeImageName:$version --build-arg TARGETARCH=$arch -f Dockerfile-ray-node .
docker build -t $rayNodeImageName:$version-py310 --build-arg TARGETARCH=$arch --build-arg IMAGE_PY_VERSION=py310 -f Dockerfile-ray-node .
docker build -t $rayNodeImageName:$version-py39  --build-arg TARGETARCH=$arch --build-arg IMAGE_PY_VERSION=py39  -f Dockerfile-ray-node .
docker build -t $gatewayImageName:$version -f ./gateway/Dockerfile .
docker build -t $proxyImageName:$version -f ./proxy/Dockerfile .

docker images
echo "end"
