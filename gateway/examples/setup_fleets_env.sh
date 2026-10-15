#!/bin/bash

# Setup environment for local Fleets testing with docker-compose.
# Builds CE_PROJECTS JSON from individual values and writes a .env file
# that docker-compose-dev.yaml can consume.
#
# Prerequisites:
#   - QC_MASTER_API_KEY env var set to your IBM Cloud API key
#
# Usage:
#   source gateway/examples/setup_fleets_env.sh

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"

# --- Validate prerequisites ---
if [ -z "$QC_MASTER_API_KEY" ]; then
    echo "Error: QC_MASTER_API_KEY is not set."
    echo "  export QC_MASTER_API_KEY='your-ibm-cloud-api-key'"
    return 1 2>/dev/null || exit 1
fi

# --- CE Project configuration ---
# These values define a single CE project. For multiple projects,
# add more entries to the CE_PROJECTS JSON array below.
CE_PROJECT_ID="5fc1f450-66c2-4745-9761-3850f9e74d84"
CE_PROJECT_NAME="qiskit-functions"
CE_REGION="us-east"
CE_RESOURCE_GROUP_ID="673b40aef2164977b31bf763a01dbba3"
# CE_SUBNET_POOL_ID="c2d873c5-1ab4-493c-b1cc-3b2da0b4d562"
CE_SUBNET_POOL_ID="c619609e-2eb3-42a7-9237-adfa52573d3e"
CE_PDS_NAME_STATE="qiskit-functions-fleet-pds"
CE_PDS_NAME_USERS="qiskit-function-user-pds"
CE_PDS_NAME_PROVIDERS="qiskit-function-provider-pds"
CE_COS_INSTANCE_NAME="qiskit-functions-ce-instance-staging"
CE_COS_KEY_NAME="qiskit-functions-ce-cos-credentials-staging"
CE_COS_BUCKET_TASK_STORE_NAME="qiskit-functions-ce-fleet-task-store-bucket-staging"
CE_COS_BUCKET_USER_DATA_NAME="qiskit-functions-ce-user-data-bucket-staging"
CE_COS_BUCKET_PROVIDER_DATA_NAME="qiskit-functions-ce-provider-data-bucket-staging"

# --- Credentials ---
IBM_CLOUD_API_KEY="${QC_MASTER_API_KEY}"
CE_HMAC_SECRET_NAME="cos-hmac-credential"
CE_ICR_PULL_SECRET="icr-pull-secret"
FLEETS_DEFAULT_IMAGE="private.icr.io/qc-qiskit-functions-ce-staging/test-local-provider-function:latest"

# --- Build CE_PROJECTS JSON ---
CE_PROJECTS="[{\"project_id\":\"${CE_PROJECT_ID}\",\"project_name\":\"${CE_PROJECT_NAME}\",\"region\":\"${CE_REGION}\",\"resource_group_id\":\"${CE_RESOURCE_GROUP_ID}\",\"subnet_pool_id\":\"${CE_SUBNET_POOL_ID}\",\"pds_name_state\":\"${CE_PDS_NAME_STATE}\",\"pds_name_users\":\"${CE_PDS_NAME_USERS}\",\"pds_name_providers\":\"${CE_PDS_NAME_PROVIDERS}\",\"cos_instance_name\":\"${CE_COS_INSTANCE_NAME}\",\"cos_key_name\":\"${CE_COS_KEY_NAME}\",\"cos_bucket_task_store_name\":\"${CE_COS_BUCKET_TASK_STORE_NAME}\",\"cos_bucket_user_data_name\":\"${CE_COS_BUCKET_USER_DATA_NAME}\",\"cos_bucket_provider_data_name\":\"${CE_COS_BUCKET_PROVIDER_DATA_NAME}\"}]"

# --- Export for shell (local dev without docker) ---
export IBM_CLOUD_API_KEY
export CE_HMAC_SECRET_NAME
export CE_ICR_PULL_SECRET
export CE_DEFAULT_PROJECT_NAME="${CE_PROJECT_NAME}"
export CE_PROJECTS
export FLEETS_DEFAULT_IMAGE
export CE_COS_USE_PUBLIC_ENDPOINT="true"

# --- Write .env for docker-compose ---
ENV_FILE="$REPO_ROOT/.env"

cat > "$ENV_FILE" << EOF
IBM_CLOUD_API_KEY=${IBM_CLOUD_API_KEY}
CE_HMAC_SECRET_NAME=${CE_HMAC_SECRET_NAME}
CE_ICR_PULL_SECRET=${CE_ICR_PULL_SECRET}
CE_DEFAULT_PROJECT_NAME=${CE_PROJECT_NAME}
CE_PROJECTS=${CE_PROJECTS}
FLEETS_DEFAULT_IMAGE=${FLEETS_DEFAULT_IMAGE}
CE_COS_USE_PUBLIC_ENDPOINT=true
EOF

echo "=== Fleets Environment Configured ==="
echo "CE_PROJECTS: 1 project (${CE_PROJECT_NAME} / ${CE_REGION})"
echo "IBM_CLOUD_API_KEY: ${IBM_CLOUD_API_KEY:0:10}..."
echo ".env written to: $ENV_FILE"
