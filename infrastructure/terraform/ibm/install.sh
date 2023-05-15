#!/bin/bash

# Introduction
echo "This script will guide you to create a Kubernetes Cluster in IBM Cloud"

# We check for the API Token needed to log-in in IBM Cloud
if [ -z "$IBMCLOUD_API_TOKEN" ]
then
  read -p "
  Introduce your IBM Cloud API Token: " IBMCLOUD_API_TOKEN
fi

# IBM Cloud CLI check
if ! command -v ibmcloud &> /dev/null
then
    echo "
    IBM Cloud CLI not found. Please install it to continue."
    exit 1
fi

# Terraform check
if ! command -v ibmcloud &> /dev/null
then
    echo "
    IBM Cloud CLI not found. Please install it to continue."
    exit 1
fi

# Log-in in IBM Cloud with API Token
ibmcloud login --apikey "$IBMCLOUD_API_TOKEN"
if [ "$?" -ne 0 ]
then
  echo "
  There was an error trying to log-in in IBM Cloud. Please review your API Token."
fi

# Execute terraform
terraform apply -auto-approve
if [ "$?" -ne 0 ]
then
  echo "
  There was a problem creating your cluster."
fi

# We do log-in in the cluster
CLUSTER_ID=$(terraform output -raw cluster_id)

ibmcloud ks cluster config --cluster "$CLUSTER_ID"

kubectl config current-context
