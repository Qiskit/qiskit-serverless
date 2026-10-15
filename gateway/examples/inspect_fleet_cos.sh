#!/bin/bash

# Inspect COS objects and PDS state for a CE Fleet job.
# Lists objects in user/provider/task-store buckets to understand
# what the fleet writes during execution and how status can be
# inferred from COS state.
#
# Prerequisites:
#   - IBM Cloud CLI with cos plugin installed
#   - QC_MASTER_API_KEY env var set
#   - A fleet job already submitted (get job_id from test output)
#
# Usage:
#   bash gateway/examples/inspect_fleet_cos.sh [job_id] [username]
#
# If job_id is omitted, lists recent objects across all buckets.

set -e

if [ -z "$QC_MASTER_API_KEY" ]; then
    echo "Error: QC_MASTER_API_KEY is not set."
    exit 1
fi

JOB_ID="${1:-}"
USERNAME="${2:-mockuser}"

CE_REGION="us-east"
CE_RESOURCE_GROUP_NAME="qiskit-functions-ce-staging"
CE_PROJECT_NAME="qiskit-functions"
CE_COS_INSTANCE_NAME="qiskit-functions-ce-instance-staging"

BUCKET_USER="qiskit-functions-ce-user-data-bucket-staging"
BUCKET_PROVIDER="qiskit-functions-ce-provider-data-bucket-staging"
BUCKET_TASK_STORE="qiskit-functions-ce-fleet-task-store-bucket-staging"

echo "=== Logging into IBM Cloud ==="
ibmcloud login --apikey "$QC_MASTER_API_KEY" -r "$CE_REGION" -g "$CE_RESOURCE_GROUP_NAME" --quiet

# Get COS instance CRN for the cos plugin
COS_CRN=$(ibmcloud resource service-instance "$CE_COS_INSTANCE_NAME" --output json | jq -r '.[0].crn // .[0].id // empty')
if [ -z "$COS_CRN" ]; then
    echo "Error: Could not find COS instance CRN"
    exit 1
fi
ibmcloud cos config crn --crn "$COS_CRN" --force

echo ""
echo "==========================================="
echo "  COS Inspection for Fleet Jobs"
echo "==========================================="

if [ -n "$JOB_ID" ]; then
    echo "  Job ID:   $JOB_ID"
    echo "  Username: $USERNAME"
    echo "==========================================="

    echo ""
    echo "--- User Bucket: $BUCKET_USER ---"
    echo "  (job-scoped: arguments, logs, results)"
    ibmcloud cos objects --bucket "$BUCKET_USER" --prefix "users/$USERNAME/" --output json 2>/dev/null | \
        jq -r '.Contents[]? | "  \(.LastModified)  \(.Size | tostring | " " * (10 - length))\(.)  \(.Key)"' | \
        grep "$JOB_ID" || echo "  (no objects found for this job)"

    echo ""
    echo "--- Provider Bucket: $BUCKET_PROVIDER ---"
    echo "  (function-scoped: entrypoint, wrapper)"
    ibmcloud cos objects --bucket "$BUCKET_PROVIDER" --prefix "providers/" --output json 2>/dev/null | \
        jq -r '.Contents[]? | "  \(.LastModified)  \(.Size | tostring | " " * (10 - length))\(.)  \(.Key)"' | \
        grep "$JOB_ID" || echo "  (no objects found for this job)"

    echo ""
    echo "--- Task Store Bucket: $BUCKET_TASK_STORE ---"
    echo "  (CE Fleets task state — status updates written here)"
    ibmcloud cos objects --bucket "$BUCKET_TASK_STORE" --prefix "" --output json 2>/dev/null | \
        jq -r '.Contents[]? | "  \(.LastModified)  \(.Size | tostring | " " * (10 - length))\(.)  \(.Key)"' | \
        grep "$JOB_ID" || echo "  (no objects found for this job)"

else
    echo "  No job_id specified — listing recent objects in all buckets"
    echo "==========================================="

    echo ""
    echo "--- User Bucket: $BUCKET_USER (last 20) ---"
    ibmcloud cos objects --bucket "$BUCKET_USER" --output json 2>/dev/null | \
        jq -r '.Contents[]? | "  \(.LastModified)  \(.Size | tostring | " " * (10 - length))\(.)  \(.Key)"' | tail -20

    echo ""
    echo "--- Provider Bucket: $BUCKET_PROVIDER (last 20) ---"
    ibmcloud cos objects --bucket "$BUCKET_PROVIDER" --output json 2>/dev/null | \
        jq -r '.Contents[]? | "  \(.LastModified)  \(.Size | tostring | " " * (10 - length))\(.)  \(.Key)"' | tail -20

    echo ""
    echo "--- Task Store Bucket: $BUCKET_TASK_STORE (all) ---"
    echo "  (This is where CE Fleets writes task status)"
    ibmcloud cos objects --bucket "$BUCKET_TASK_STORE" --output json 2>/dev/null | \
        jq -r '.Contents[]? | "  \(.LastModified)  \(.Size | tostring | " " * (10 - length))\(.)  \(.Key)"' | tail -30
fi

echo ""
echo "==========================================="
echo "  Fleet Status via CE CLI"
echo "==========================================="
ibmcloud ce project select -n "$CE_PROJECT_NAME" --quiet 2>/dev/null
echo ""
echo "--- Active Fleets ---"
ibmcloud ce fleet list --output json 2>/dev/null | jq -r '.[] | "  \(.name)  status=\(.status)  created=\(.created_at)"' | head -10 || echo "  (none or error)"
