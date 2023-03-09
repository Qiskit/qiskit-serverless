#!/bin/bash
LOCAL_IP=$1
kubectl patch deployments kuberay-apiserver --type=json -p='[{"op": "add", "path": "/spec/template/spec/containers/-","value":{"image": "quay.io/gogatekeeper/gatekeeper:2.1.1","imagePullPolicy": "IfNotPresent","name": "gatekeeper","args":["--no-redirects=true","--forwarding-grant-type=client_credentials","--listen=0.0.0.0:4180","--client-id=rayapiserver","--client-secret=APISERVERSECRET-CHANGEME","--discovery-url=http://'$LOCAL_IP':31059/realms/quantumserverless","--enable-logging=true","--verbose=true","--upstream-url=http://kuberay-apiserver-service:8888/"]}}]'
