#!/bin/bash

# Introduction
echo "This script will help you install quantum-serverless using helm in IBM Cloud."

# Requirements validation step
echo "
The script is checking that you have all the needed requirements...".

# Helm check
if ! command -v helm &> /dev/null
then
    echo "
    Helm not found. Please install helm to continue."
    exit 1
fi

# Cluster check
if ! kubectl cluster-info &> /dev/null
then
    echo "
    There is no connectivity with a valid cluster in the current context. Please verify that you are connected with the desired cluster."
    exit 1
fi

# Ask for the minimum information to configure the values
echo "
All the requirements all fulfilled. Please provide to quantum-serverless the next information to continue:"
read -p "* Ingress public end-point of your cluster: " INGRESS_PUBLIC_END_POINT
read -p "* Your Ingress' secret: " INGRESS_SECRET
read -p "* Gateway's API secret: " GATEWAY_SECRET
read -p "* Grafana's secret: " GRAFANA_SECRET

# Variables definition
GATEWAY_HOST="gateway.$INGRESS_PUBLIC_END_POINT"
REPOSITORY_HOST="repository.$INGRESS_PUBLIC_END_POINT"

# Helm execution
helm upgrade \
  --namespace quantum-serverless \
  --values values-ibm.yaml \
  --set-string ingress.tls[0].hosts="{$GATEWAY_HOST,$REPOSITORY_HOST}" \
  --set ingress.tls[0].secretName="$INGRESS_SECRET" \
  --set ingress.hosts[0].host="$GATEWAY_HOST" \
  --set ingress.hosts[1].host="$REPOSITORY_HOST" \
  --set gateway.application.keycloak.clientSecret="$GATEWAY_SECRET" \
  --set kube-prometheus-stack.grafana.grafana\\.ini.auth\\.generic_oauth.client_secret="$GRAFANA_SECRET" \
  --install \
  --create-namespace \
  --atomic \
  --debug \
  quantum-serverless .
