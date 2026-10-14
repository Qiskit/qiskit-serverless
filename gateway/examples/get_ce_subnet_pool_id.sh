#!/bin/bash

# Retrieves dynamic IDs from an IBM Cloud Code Engine project.
#
# Prerequisites:
#   - IBM Cloud CLI installed with the code-engine plugin
#   - QC_MASTER_API_KEY env var set to your IBM Cloud API key
#
# Usage:
#   bash gateway/examples/get_ce_subnet_pool_id.sh

set -e

if [ -z "$QC_MASTER_API_KEY" ]; then
    echo "Error: QC_MASTER_API_KEY is not set."
    echo "  export QC_MASTER_API_KEY='your-ibm-cloud-api-key'"
    exit 1
fi

CE_REGION="us-east"
CE_RESOURCE_GROUP_NAME="qiskit-functions-ce-staging"
CE_PROJECT_NAME="qiskit-functions"
CE_COS_INSTANCE_NAME="qiskit-functions-ce-instance-staging"

echo "Logging into IBM Cloud (region: ${CE_REGION})..."
ibmcloud login --apikey "$QC_MASTER_API_KEY" -r "$CE_REGION" --quiet

# --- Resource Group ID ---
echo "Fetching resource group ID..."
CE_RESOURCE_GROUP_ID=$(ibmcloud resource groups --output json | jq -r --arg name "$CE_RESOURCE_GROUP_NAME" '.[] | select(.name == $name) | .id')

echo "Targeting resource group: ${CE_RESOURCE_GROUP_NAME}..."
ibmcloud target -g "$CE_RESOURCE_GROUP_NAME" --quiet

# --- Project ID ---
echo "Fetching CE project ID..."
CE_PROJECT_ID=$(ibmcloud ce project list --output json | jq -r --arg name "$CE_PROJECT_NAME" '.[] | select(.name == $name) | .guid')

# --- Subnet Pool ID ---
echo "Selecting CE project: ${CE_PROJECT_NAME}..."
ibmcloud ce project select -n "$CE_PROJECT_NAME" --quiet

echo "Fetching subnet pool ID..."
SUBNETPOOL_JSON=$(ibmcloud ce connectivity subnetpool list --output json)
CE_SUBNET_POOL_ID=$(echo "$SUBNETPOOL_JSON" | jq -r '.subnetpools[0].id // .items[0].id // .subnet_pools[0].id // ([.. | .id? // empty] | first) // empty' 2>/dev/null)

if [ -z "$CE_SUBNET_POOL_ID" ]; then
    echo "Warning: could not parse subnet pool ID. Raw JSON:"
    echo "$SUBNETPOOL_JSON" | jq .
    exit 1
fi

# --- COS Instance ID ---
echo "Fetching COS instance ID..."
CE_COS_INSTANCE_ID=$(ibmcloud resource service-instances --output json | jq -r --arg name "$CE_COS_INSTANCE_NAME" '.[] | select(.name == $name) | .id')

# --- Pretty print ---
echo ""
echo "==========================================="
echo "  Code Engine Project IDs"
echo "==========================================="
printf "  %-25s %s\n" "Region:" "$CE_REGION"
printf "  %-25s %s\n" "Resource Group:" "$CE_RESOURCE_GROUP_NAME"
printf "  %-25s %s\n" "CE Project:" "$CE_PROJECT_NAME"
echo "-------------------------------------------"
printf "  %-25s %s\n" "CE_RESOURCE_GROUP_ID:" "$CE_RESOURCE_GROUP_ID"
printf "  %-25s %s\n" "CE_PROJECT_ID:" "$CE_PROJECT_ID"
printf "  %-25s %s\n" "CE_SUBNET_POOL_ID:" "$CE_SUBNET_POOL_ID"
printf "  %-25s %s\n" "CE_COS_INSTANCE_ID:" "$CE_COS_INSTANCE_ID"
echo "==========================================="
