#!/bin/bash

# Create a Code Engine Fleet directly via the IBM Cloud CLI, then verify it
# by downloading its result object from COS.
#
# This is a smoke test for fleet creation that bypasses the Gateway: it
# reuses the configuration defined in setup_fleets_env.sh and the login /
# targeting flow from get_ce_subnet_pool_id.sh, then calls
# `ibmcloud ce fleet create` (mirroring IBM/CodeEngine serverless-fleets/run).
#
# It mounts the user-data persistent data store at /job_user_data (mirroring
# the Gateway's JOB_USER_DATA_PATH for custom-function jobs) under a job-scoped
# COS prefix. The task writes its output to /job_user_data/results.json, which
# lands in COS at <prefix>/results.json. After the fleet finishes, the script
# downloads that object with the COS CLI (as in inspect_fleet_cos.sh) and prints
# it so you can verify the result end to end.
#
# Prerequisites:
#   - IBM Cloud CLI with the code-engine plugin installed
#   - jq, python3, curl, uuidgen installed
#   - QC_MASTER_API_KEY env var set to your IBM Cloud API key
#
# Usage:
#   bash gateway/examples/create_ce_fleet.sh
#
# Optional overrides (env vars):
#   CE_RESOURCE_GROUP_NAME   Resource group to target (default: qiskit-functions-ce-staging)
#   FLEET_IMAGE              Container image (default: FLEETS_DEFAULT_IMAGE from setup_fleets_env.sh,
#                            a private ICR image reachable from the fleet's private network)
#   FLEET_CPU                vCPUs per task (default: 2)
#   FLEET_MEMORY             Memory per task (default: 4G)
#   FLEET_TASKS              Number of tasks (default: 1)
#   FLEET_MAX_SCALE          Max parallel task instances (default: 1)
#   FLEET_COMMAND            Command to run in the task (default: python)
#   FLEET_PYTHON_CODE        Code run via `python -c` (default: writes results to the mount + prints)
#   FLEET_USER               Pseudo username for the COS prefix (default: smoketest)
#   FLEET_FUNCTION           Pseudo function title for the COS prefix (default: ce-fleet-smoke-test)
#   FLEET_NAME               Override the generated fleet name (also used as the job id)
#   --- Worker startup hooks (experimental __CE_INTERNAL_*; all optional) ---
#   FLEET_HOOK_AFTER_STARTUP Script body run on the worker before tasks start
#   FLEET_HOOK_RETRY_LIMIT   Hook retry attempts (default: 3; only applied when hook set)
#   FLEET_HOOK_MAX_EXEC_TIME Max hook runtime, e.g. 10m (default: 10m; only when hook set)
#   FLEET_PRIVILEGED=true    Run the worker container privileged (nested containers)
#   FLEET_HOSTPATH_MOUNTS    Host path mounts HOST:CONTAINER[,HOST:CONTAINER...]
#   VERIFY=0                 Skip waiting + COS download; just submit the fleet
#   VERIFY_TIMEOUT           Seconds to wait for the fleet to finish (default: 1800;
#                            worker provisioning alone can take ~10-15 min)
#   POLL_INTERVAL            Seconds between status polls (default: 20)
#   CLEANUP=1                Delete the fleet after verifying
#   DRY_RUN=1                Print the fleet create command without running it

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Required tooling ---
for _cmd in ibmcloud jq python3 curl uuidgen; do
    command -v "$_cmd" >/dev/null || { echo "Error: required command '$_cmd' not found."; exit 1; }
done

# --- Load configuration (validates QC_MASTER_API_KEY, exports CE_* vars) ---
echo "=== Loading Fleets configuration ==="
# shellcheck source=setup_fleets_env.sh
source "$SCRIPT_DIR/setup_fleets_env.sh"

# --- Resolve project fields from the CE_PROJECTS JSON ---
PROJECT_JSON=$(echo "$CE_PROJECTS" | jq -r '.[0]')
CE_PROJECT_NAME=$(echo "$PROJECT_JSON" | jq -r '.project_name')
CE_REGION=$(echo "$PROJECT_JSON" | jq -r '.region')
CE_SUBNET_POOL_ID=$(echo "$PROJECT_JSON" | jq -r '.subnet_pool_id')
CE_PDS_NAME_STATE=$(echo "$PROJECT_JSON" | jq -r '.pds_name_state')
CE_PDS_NAME_USERS=$(echo "$PROJECT_JSON" | jq -r '.pds_name_users')
CE_COS_BUCKET_USER_DATA_NAME=$(echo "$PROJECT_JSON" | jq -r '.cos_bucket_user_data_name')

# jq emits the string "null" for missing keys — fail fast on anything required.
for _var in CE_PROJECT_NAME CE_REGION CE_SUBNET_POOL_ID CE_PDS_NAME_STATE \
            CE_PDS_NAME_USERS CE_COS_BUCKET_USER_DATA_NAME; do
    _val="${!_var}"
    if [ -z "$_val" ] || [ "$_val" = "null" ]; then
        echo "Error: $_var is missing from CE_PROJECTS in setup_fleets_env.sh."
        exit 1
    fi
done

# setup_fleets_env.sh carries the resource group ID, but login/target use the
# name (as in get_ce_subnet_pool_id.sh). Override via CE_RESOURCE_GROUP_NAME.
CE_RESOURCE_GROUP_NAME="${CE_RESOURCE_GROUP_NAME:-qiskit-functions-ce-staging}"

# --- Fleet parameters (override via env) ---
# Default to the private ICR provider image (from setup_fleets_env.sh). The
# fleet's subnet pool reaches IBM Container Registry over the private network
# but has NO egress to docker.io, so public images (e.g. python:3.11-slim)
# cannot be pulled by the worker. This image is python-based, so `python -c`
# runs on it; the *.icr.io pull secret is attached automatically below.
FLEET_IMAGE="${FLEET_IMAGE:-$FLEETS_DEFAULT_IMAGE}"
FLEET_CPU="${FLEET_CPU:-2}"
FLEET_MEMORY="${FLEET_MEMORY:-4G}"
FLEET_TASKS="${FLEET_TASKS:-1}"
FLEET_MAX_SCALE="${FLEET_MAX_SCALE:-1}"
FLEET_COMMAND="${FLEET_COMMAND:-python}"
FLEET_USER="${FLEET_USER:-smoketest}"
FLEET_FUNCTION="${FLEET_FUNCTION:-ce-fleet-smoke-test}"
# Unique, DNS-safe fleet name (lowercase alphanumeric + hyphens). Reused as job id.
FLEET_NAME="${FLEET_NAME:-fleet-$(uuidgen | tr '[:upper:]' '[:lower:]' | cut -d- -f1)}"

# --- Mount + COS layout (mirrors core/.../fleets/utils.py custom-job paths) ---
# JOB_USER_DATA_PATH is mounted from the user-data PDS at a job-scoped COS prefix.
MOUNT_PATH="/job_user_data"
RESULT_FILENAME="results.json"
COS_PREFIX="users/${FLEET_USER}/custom_functions/${FLEET_FUNCTION}/jobs/${FLEET_NAME}"
CONTAINER_RESULT_PATH="${MOUNT_PATH}/${RESULT_FILENAME}"   # written by the task
COS_RESULT_KEY="${COS_PREFIX}/${RESULT_FILENAME}"          # downloaded for verification

# Default task: write its output to the mounted result path (so it lands in COS),
# and also echo to stdout for the CE logs.
DEFAULT_PYTHON_CODE="import sys; msg='Hello from Code Engine fleet, running '+sys.version; print(msg); open('${CONTAINER_RESULT_PATH}','w').write(msg)"
FLEET_PYTHON_CODE="${FLEET_PYTHON_CODE:-$DEFAULT_PYTHON_CODE}"

# CE rejects literal newlines in a run-argument value ("run_arguments[N].type
# ... REGEXP"). Send the python INLINE (no encoding) as a single-line exec() of
# a plaintext string literal: json.dumps turns newlines into \n escapes and
# safely quotes the source, so multi-line code with loops/quotes works as-is
# while staying readable in the fleet spec. NB: this assumes FLEET_COMMAND is a
# Python interpreter (the default); override both if you run something else.
PY_LITERAL=$(printf '%s' "$FLEET_PYTHON_CODE" | python3 -c 'import sys, json; print(json.dumps(sys.stdin.read()))')
PY_BOOTSTRAP="exec($PY_LITERAL)"

# Normalize the privileged flag once (accept "true" or "1").
PRIVILEGED=0
case "${FLEET_PRIVILEGED:-0}" in true|1) PRIVILEGED=1 ;; esac

# --- Optional worker startup hook / privileged / hostpath (experimental) ---
# Map to Code Engine's __CE_INTERNAL_* env vars. Empty unless the env is set, so
# this is a no-op for the default smoke test. Use the --env=NAME=VALUE form so a
# multi-line script body stays a single CLI token.
HOOK_ARGS=()
if [ -n "${FLEET_HOOK_AFTER_STARTUP:-}" ]; then
    HOOK_ARGS+=( "--env=__CE_INTERNAL_HOOK_AFTER_STARTUP=$FLEET_HOOK_AFTER_STARTUP" )
    HOOK_ARGS+=( "--env=__CE_INTERNAL_HOOK_AFTER_STARTUP_RETRY_LIMIT=${FLEET_HOOK_RETRY_LIMIT:-3}" )
    HOOK_ARGS+=( "--env=__CE_INTERNAL_HOOK_AFTER_STARTUP_MAX_EXECUTION_TIME=${FLEET_HOOK_MAX_EXEC_TIME:-10m}" )
fi
if [ "$PRIVILEGED" = 1 ]; then
    HOOK_ARGS+=( "--env=__CE_INTERNAL_PRIVILEGED_CONTAINER=true" )
fi
if [ -n "${FLEET_HOSTPATH_MOUNTS:-}" ]; then
    HOOK_ARGS+=( "--env=__CE_INTERNAL_HOSTPATH_MOUNTS=$FLEET_HOSTPATH_MOUNTS" )
fi

# --- Build the fleet create command ---
# Private images (private.icr.io / *.icr.io) need a registry pull secret.
REGISTRY_SECRET_ARGS=()
case "$FLEET_IMAGE" in
    *.icr.io/*|private.icr.io/*)
        REGISTRY_SECRET_ARGS=(--registry-secret "$CE_ICR_PULL_SECRET")
        ;;
esac

# Use the --flag=value form for arguments so a value beginning with '-'
# (e.g. "-c") is not mistaken for a flag by the CLI parser.
FLEET_CMD=(
    ibmcloud ce fleet create
    --name "$FLEET_NAME"
    --image "$FLEET_IMAGE"
    --tasks-state-store "$CE_PDS_NAME_STATE"
    --subnetpool-id "$CE_SUBNET_POOL_ID"
    --mount-data-store "${MOUNT_PATH}=${CE_PDS_NAME_USERS}:${COS_PREFIX}"
    --tasks "$FLEET_TASKS"
    --max-scale "$FLEET_MAX_SCALE"
    --cpu "$FLEET_CPU"
    --memory "$FLEET_MEMORY"
    --command "$FLEET_COMMAND"
    "--argument=-c"
    "--argument=$PY_BOOTSTRAP"
    "${HOOK_ARGS[@]}"
    "${REGISTRY_SECRET_ARGS[@]}"
)

echo ""
echo "==========================================="
echo "  Creating Code Engine Fleet"
echo "==========================================="
printf "  %-22s %s\n" "Fleet name:" "$FLEET_NAME"
printf "  %-22s %s\n" "Project:" "$CE_PROJECT_NAME"
printf "  %-22s %s\n" "Image:" "$FLEET_IMAGE"
printf "  %-22s %s\n" "Tasks state store:" "$CE_PDS_NAME_STATE"
printf "  %-22s %s\n" "Subnet pool ID:" "$CE_SUBNET_POOL_ID"
printf "  %-22s %s\n" "Mount:" "${MOUNT_PATH} <- ${CE_PDS_NAME_USERS}:${COS_PREFIX}"
printf "  %-22s %s\n" "CPU / Memory:" "$FLEET_CPU / $FLEET_MEMORY"
printf "  %-22s %s\n" "Tasks / Max scale:" "$FLEET_TASKS / $FLEET_MAX_SCALE"
printf "  %-22s %s\n" "Command:" "$FLEET_COMMAND -c '$FLEET_PYTHON_CODE'"
printf "  %-22s %s\n" "Result COS key:" "${CE_COS_BUCKET_USER_DATA_NAME}/${COS_RESULT_KEY}"
if [ -n "${FLEET_HOOK_AFTER_STARTUP:-}" ]; then
    printf "  %-22s %s\n" "After-startup hook:" "set (max ${FLEET_HOOK_MAX_EXEC_TIME:-10m}, retry ${FLEET_HOOK_RETRY_LIMIT:-3})"
fi
if [ "$PRIVILEGED" = 1 ]; then
    printf "  %-22s %s\n" "Privileged:" "true"
fi
if [ -n "${FLEET_HOSTPATH_MOUNTS:-}" ]; then
    printf "  %-22s %s\n" "Hostpath mounts:" "$FLEET_HOSTPATH_MOUNTS"
fi
echo "==========================================="
echo ""
echo "+ ${FLEET_CMD[*]}"

if [ "${DRY_RUN:-0}" = "1" ]; then
    echo ""
    echo "DRY_RUN=1 — not logging in or executing."
    exit 0
fi

# --- Login + target (same flow as get_ce_subnet_pool_id.sh) ---
echo ""
echo "=== Logging into IBM Cloud (region: ${CE_REGION}) ==="
ibmcloud login --apikey "$QC_MASTER_API_KEY" -r "$CE_REGION" --quiet

echo "Targeting resource group: ${CE_RESOURCE_GROUP_NAME}..."
ibmcloud target -g "$CE_RESOURCE_GROUP_NAME" --quiet

echo "Selecting CE project: ${CE_PROJECT_NAME}..."
ibmcloud ce project select -n "$CE_PROJECT_NAME" --quiet

echo ""
CREATE_OUT=$("${FLEET_CMD[@]}" 2>&1) || { echo "$CREATE_OUT"; exit 1; }
echo "$CREATE_OUT"

echo ""
echo "=== Fleet '${FLEET_NAME}' submitted ==="

if [ "${VERIFY:-1}" != "1" ]; then
    echo ""
    echo "VERIFY=0 — skipping wait + COS download."
    echo "  List:    ibmcloud ce fleet list"
    echo "  (fleet get/delete require --id; resolve it from the list above)"
    exit 0
fi

# --- Resolve the fleet id ---
# `fleet create` prints "... and ID '<uuid>'"; parse it. Fall back to the
# fleet list (returns {"fleets": [...]}) if the output format ever changes.
echo ""
echo "=== Resolving fleet id ==="
FLEET_ID=$(printf '%s\n' "$CREATE_OUT" | sed -nE "s/.*ID '([0-9a-fA-F-]{36})'.*/\1/p" | head -1)
if [ -z "$FLEET_ID" ]; then
    for _ in $(seq 1 12); do
        FLEET_ID=$(ibmcloud ce fleet list --output json 2>/dev/null \
            | jq -r --arg n "$FLEET_NAME" '.fleets[]? | select(.name==$n) | .id' | head -1) || true
        if [ -n "$FLEET_ID" ] && [ "$FLEET_ID" != "null" ]; then
            break
        fi
        sleep 5
    done
fi
if [ -z "$FLEET_ID" ] || [ "$FLEET_ID" = "null" ]; then
    echo "Error: could not resolve id for fleet '$FLEET_NAME'."
    exit 1
fi
echo "Fleet id: $FLEET_ID"

# --- Poll until the fleet reaches a terminal state ---
VERIFY_TIMEOUT="${VERIFY_TIMEOUT:-1800}"
POLL_INTERVAL="${POLL_INTERVAL:-20}"
echo ""
echo "=== Waiting for fleet to finish (timeout: ${VERIFY_TIMEOUT}s) ==="
echo "    (provisioning a fleet worker can take several minutes)"
STATUS=""
LAST_STATUS="__none__"
DEADLINE=$(( SECONDS + VERIFY_TIMEOUT ))
while [ "$SECONDS" -lt "$DEADLINE" ]; do
    STATUS=$(ibmcloud ce fleet get --id "$FLEET_ID" --output json 2>/dev/null \
        | jq -r '.fleet.status // empty') || true
    if [ "$STATUS" != "$LAST_STATUS" ]; then
        echo "  status: ${STATUS:-<unknown>}"
        LAST_STATUS="$STATUS"
    fi
    case "$STATUS" in
        succeeded|successful|failed|canceled) break ;;
    esac
    sleep "$POLL_INTERVAL"
done

case "$STATUS" in
    succeeded|successful) ;;
    *)
        echo ""
        echo "Fleet did not succeed (last status: ${STATUS:-<unknown>})."
        echo "Task details:"
        ibmcloud ce fleet task list --fleet-id "$FLEET_ID" --output json 2>/dev/null \
            | jq -r '.tasks[]? | "  task \(.index): \(.status) — \(.status_details.reason // .status_details.result_code // "no detail")"' || true
        echo "  Inspect:  ibmcloud ce fleet get    --id ${FLEET_ID}"
        echo "  Delete:   ibmcloud ce fleet delete --id ${FLEET_ID} --force"
        exit 1
        ;;
esac

# --- Download the result object from COS ---
# Use an authenticated GET against the S3 endpoint with an IAM bearer token
# rather than `ibmcloud cos object-get`: the latter reliably hangs on the data
# transfer from some networks, while a plain HTTPS GET is fast and robust.
echo ""
echo "=== Downloading result from COS ==="
COS_ENDPOINT="${CE_COS_ENDPOINT:-https://s3.${CE_REGION}.cloud-object-storage.appdomain.cloud}"
IAM_TOKEN=$(ibmcloud iam oauth-tokens --output json 2>/dev/null | jq -r '.iam_token') || true
if [ -z "$IAM_TOKEN" ] || [ "$IAM_TOKEN" = "null" ]; then
    echo "Error: could not obtain an IAM token for the COS download."
    exit 1
fi

LOCAL_OUT="$(mktemp)"
trap 'rm -f "$LOCAL_OUT"' EXIT
# Retry until the object is present AND non-empty: the PDS->COS sync can lag the
# fleet's "successful" status by a minute or more (404 / 0 bytes until then).
DOWNLOAD_OK=0
for _ in $(seq 1 24); do
    if curl -fsS --max-time 20 -H "Authorization: $IAM_TOKEN" \
            "${COS_ENDPOINT}/${CE_COS_BUCKET_USER_DATA_NAME}/${COS_RESULT_KEY}" \
            -o "$LOCAL_OUT" 2>/dev/null && [ -s "$LOCAL_OUT" ]; then
        DOWNLOAD_OK=1
        break
    fi
    sleep 5
done
if [ "$DOWNLOAD_OK" = "1" ]; then
    echo "Downloaded: ${CE_COS_BUCKET_USER_DATA_NAME}/${COS_RESULT_KEY} ($(wc -c < "$LOCAL_OUT" | tr -d ' ') bytes)"
    echo "-------------------------------------------"
    cat "$LOCAL_OUT"
    echo ""
    echo "-------------------------------------------"
    echo "=== VERIFIED: result object present and non-empty ==="
else
    echo "Error: result object missing or empty at ${CE_COS_BUCKET_USER_DATA_NAME}/${COS_RESULT_KEY}"
    echo "  List objects: ibmcloud cos objects --bucket ${CE_COS_BUCKET_USER_DATA_NAME} --prefix ${COS_PREFIX}/"
    exit 1
fi

# --- Optional cleanup ---
if [ "${CLEANUP:-0}" = "1" ]; then
    echo ""
    echo "=== Deleting fleet (CLEANUP=1) ==="
    # Request deletion without --wait; it completes server-side in the background.
    ibmcloud ce fleet delete --id "$FLEET_ID" --force --ignore-not-found \
        || echo "  (delete request returned non-zero; check: ibmcloud ce fleet get --id $FLEET_ID)"
else
    echo ""
    echo "Fleet kept. To remove it:"
    echo "  ibmcloud ce fleet delete --id ${FLEET_ID} --force"
fi
