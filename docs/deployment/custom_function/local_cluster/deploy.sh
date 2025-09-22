#! /bin/bash

set -ex

cat <<EOF | kind create cluster --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  image: kindest/node:v1.29.4
  kubeadmConfigPatches:
  - |
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        node-labels: "ingress-ready=true"
  extraPortMappings:
  - containerPort: 80
    hostPort: 80
    protocol: TCP
  - containerPort: 443
    hostPort: 443
    protocol: TCP
EOF

kubectl label node kind-control-plane has-gpu=gpu has-cpu=cpu
kubectl apply -f https://kind.sigs.k8s.io/examples/ingress/deploy-ingress-nginx.yaml

docker build -t gateway:test -f ./gateway/Dockerfile .
kind load docker-image gateway:test
docker image rm gateway:test

docker build -t ray:test -f ./Dockerfile-ray-node .
kind load docker-image ray:test
docker image rm ray:test

cd charts/qiskit-serverless
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo add kuberay https://ray-project.github.io/kuberay-helm
helm dependency build
helm install qs \
--set platform=kind \
--set nginxIngressControllerEnable=false \
--set gateway.image.repository=gateway \
--set gateway.image.tag=test \
--set gateway.application.ray.nodeImage=ray:test \
--set gateway.application.ray.cpu=1 \
--set gateway.application.debug=1 \
--set gateway.application.limits.keepClusterOnComplete=false \
--set gateway.application.authMockproviderRegistry=test \
--set ingress.hosts[0].host=localhost \
--set ingress.hosts[0].paths[0].path=/ \
--set ingress.hosts[0].paths[0].pathType=Prefix \
--set ingress.hosts[0].paths[0].serviceName=gateway \
--set ingress.hosts[0].paths[0].servicePort=8000 \
--set postgresql.image.repository=bitnamilegacy/postgresql \
--set postgresql.volumePermissions.image.repository=bitnamilegacy/os-shell \
--set postgresql.metrics.image.repository=bitnamilegacy/postgres-exporter \
.

kubectl wait \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/name=gateway-scheduler \
  --timeout=5m

kubectl wait \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/name=gateway \
  --timeout=5m  

kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=5m
