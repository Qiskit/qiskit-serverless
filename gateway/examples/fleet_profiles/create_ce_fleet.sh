#!/bin/bash

# Create a single Code Engine Fleet directly via the IBM Cloud CLI and measure
# its lifecycle timings. This is the proxy-free sibling of
# gateway/examples/fleet_egress_proxy/create_ce_fleet.sh — no worker startup
# hook, no privileged container, no hostpath mounts. Its job is to submit one
# fleet with a given CPU / memory / GPU allocation and report:
#
#   provisioning_s = submit  -> running   (worker provisioning: created -> run)
#   execution_s    = running -> terminal  (task run: running -> finished)
#   total_s        = submit  -> terminal
#
# Resources are passed as raw --cpu / --memory / --gpu values (NOT
# --worker-profile). --gpu takes the CLI's FAMILY:COUNT form (e.g. l40s:1,
# a100:8); see `ibmcloud ce fleet worker profiles` for valid families.
#
# It mounts the user-data persistent data store at /job_user_data (mirroring the
# Gateway's JOB_USER_DATA_PATH) under a job-scoped COS prefix. The task writes a
# small result to /job_user_data/results.json; downloading it back from COS is
# optional (DOWNLOAD_RESULT=1) and off by default so the PDS->COS sync lag does
# not inflate the measured execution time.
#
# Prerequisites:
#   - IBM Cloud CLI with the code-engine plugin installed
#   - jq, python3, curl, uuidgen installed
#   - QC_MASTER_API_KEY env var set to your IBM Cloud API key
#
# Usage:
#   FLEET_CPU=8 FLEET_MEMORY=32G bash gateway/examples/fleet_profiles/create_ce_fleet.sh
#   FLEET_CPU=24 FLEET_MEMORY=120G FLEET_GPU=l40s:1 bash .../create_ce_fleet.sh
#
# Key env vars (see also setup_fleets_env.sh):
#   FLEET_CPU                vCPUs per task (default: 2)
#   FLEET_MEMORY             Memory per task, e.g. 32G (default: 4G)
#   FLEET_GPU                GPU allocation FAMILY:COUNT, e.g. a100:8 (default: none)
#   FLEET_PROFILE_LABEL      Label echoed in the FLEET_TIMING line (default: custom)
#   FLEET_IMAGE              Container image (default: FLEETS_DEFAULT_IMAGE)
#   FLEET_TASKS              Number of tasks (default: 1)
#   FLEET_MAX_SCALE          Max parallel task instances (default: 1)
#   FLEET_COMMAND            Command to run in the task (default: python)
#   FLEET_PYTHON_CODE        Code run via `python -c` (default: sleep + write result + print)
#   FLEET_TASK_SLEEP         Seconds the default task sleeps while running (default: 30),
#                            so execution_s (running -> finished) is measurable
#   FLEET_USER               Pseudo username for the COS prefix (default: benchmark)
#   FLEET_FUNCTION           Pseudo function title for the COS prefix (default: fleet-profiles)
#   FLEET_NAME               Override the generated fleet name (also used as job id)
#   VERIFY_TIMEOUT           Seconds to wait for the fleet to finish (default: 7200;
#                            large profiles can take a very long time to provision)
#   POLL_INTERVAL            Seconds between status polls (default: 20)
#   DOWNLOAD_RESULT=1        Also download + print the result object from COS
#   CLEANUP=1                Delete the fleet after it reaches a terminal state
#   SKIP_LOGIN=1             Skip login/target/select (caller already did it — used by the driver)
#   DRY_RUN=1                Print the fleet create command without running it

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Required tooling ---
for _cmd in ibmcloud jq python3 curl uuidgen; do
    command -v "$_cmd" >/dev/null || { echo "Error: required command '$_cmd' not found."; exit 1; }
done

# --- Load configuration (validates QC_MASTER_API_KEY, exports CE_* vars) ---
# Reuse the shared env from the parent examples folder (no duplication).
echo "=== Loading Fleets configuration ==="
# shellcheck source=../setup_fleets_env.sh
source "$SCRIPT_DIR/../setup_fleets_env.sh"

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
FLEET_IMAGE="${FLEET_IMAGE:-$FLEETS_DEFAULT_IMAGE}"
FLEET_CPU="${FLEET_CPU:-2}"
FLEET_MEMORY="${FLEET_MEMORY:-4G}"
FLEET_GPU="${FLEET_GPU:-}"                     # FAMILY:COUNT, e.g. a100:8; empty = no GPU
FLEET_PROFILE_LABEL="${FLEET_PROFILE_LABEL:-custom}"
FLEET_TASKS="${FLEET_TASKS:-1}"
FLEET_MAX_SCALE="${FLEET_MAX_SCALE:-1}"
FLEET_COMMAND="${FLEET_COMMAND:-python}"
FLEET_USER="${FLEET_USER:-benchmark}"
FLEET_FUNCTION="${FLEET_FUNCTION:-fleet-profiles}"
# Seconds the task sleeps while "running" so execution_s (running -> finished) is
# a measurable, comparable value instead of ~0 for a near-instant task.
FLEET_TASK_SLEEP="${FLEET_TASK_SLEEP:-30}"
# Unique, DNS-safe fleet name (lowercase alphanumeric + hyphens). Reused as job id.
FLEET_NAME="${FLEET_NAME:-fleet-$(uuidgen | tr '[:upper:]' '[:lower:]' | cut -d- -f1)}"

# --- Mount + COS layout (mirrors core/.../fleets/utils.py custom-job paths) ---
MOUNT_PATH="/job_user_data"
RESULT_FILENAME="results.json"
COS_PREFIX="users/${FLEET_USER}/custom_functions/${FLEET_FUNCTION}/jobs/${FLEET_NAME}"
CONTAINER_RESULT_PATH="${MOUNT_PATH}/${RESULT_FILENAME}"   # written by the task
COS_RESULT_KEY="${COS_PREFIX}/${RESULT_FILENAME}"          # downloaded for verification

# Default task: write a small JSON result to the mounted path (so it lands in
# COS) and echo to stdout for the CE logs. The payload is trivial on purpose —
# execution time here is dominated by worker run/teardown, not the task itself.
DEFAULT_PYTHON_CODE="import sys, json, time; msg='Hello from CE fleet profile ${FLEET_PROFILE_LABEL}, running '+sys.version; print(msg, flush=True); time.sleep(${FLEET_TASK_SLEEP}); open('${CONTAINER_RESULT_PATH}','w').write(json.dumps({'profile':'${FLEET_PROFILE_LABEL}','message':msg,'slept_s':${FLEET_TASK_SLEEP}}))"
FLEET_PYTHON_CODE="${FLEET_PYTHON_CODE:-$DEFAULT_PYTHON_CODE}"

# CE rejects literal newlines in a run-argument value. Send the python INLINE as
# a single-line exec() of a json.dumps'd source string (newlines -> \n escapes).
PY_LITERAL=$(printf '%s' "$FLEET_PYTHON_CODE" | python3 -c 'import sys, json; print(json.dumps(sys.stdin.read()))')
PY_BOOTSTRAP="exec($PY_LITERAL)"

# --- Optional GPU allocation ---
GPU_ARGS=()
if [ -n "$FLEET_GPU" ]; then
    GPU_ARGS=(--gpu "$FLEET_GPU")
fi

# --- Registry pull secret for private images (private.icr.io / *.icr.io) ---
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
    "${GPU_ARGS[@]}"
    --command "$FLEET_COMMAND"
    "--argument=-c"
    "--argument=$PY_BOOTSTRAP"
    "${REGISTRY_SECRET_ARGS[@]}"
)

echo ""
echo "==========================================="
echo "  Creating Code Engine Fleet"
echo "==========================================="
printf "  %-22s %s\n" "Fleet name:" "$FLEET_NAME"
printf "  %-22s %s\n" "Profile:" "$FLEET_PROFILE_LABEL"
printf "  %-22s %s\n" "Project:" "$CE_PROJECT_NAME"
printf "  %-22s %s\n" "Image:" "$FLEET_IMAGE"
printf "  %-22s %s\n" "CPU / Memory:" "$FLEET_CPU / $FLEET_MEMORY"
printf "  %-22s %s\n" "GPU:" "${FLEET_GPU:-<none>}"
printf "  %-22s %s\n" "Tasks / Max scale:" "$FLEET_TASKS / $FLEET_MAX_SCALE"
printf "  %-22s %s\n" "Result COS key:" "${CE_COS_BUCKET_USER_DATA_NAME}/${COS_RESULT_KEY}"
echo "==========================================="
echo ""
echo "+ ${FLEET_CMD[*]}"

if [ "${DRY_RUN:-0}" = "1" ]; then
    echo ""
    echo "DRY_RUN=1 — not logging in or executing."
    # Emit a placeholder timing line so the driver can parse a row in DRY_RUN too.
    echo "FLEET_TIMING profile=${FLEET_PROFILE_LABEL} cpu=${FLEET_CPU} memory=${FLEET_MEMORY} gpu=${FLEET_GPU:-none} name=${FLEET_NAME} final_status=dry_run provisioning_s=NA execution_s=NA total_s=NA"
    exit 0
fi

# --- Login + target (skip when the driver already did it) ---
if [ "${SKIP_LOGIN:-0}" != "1" ]; then
    echo ""
    echo "=== Logging into IBM Cloud (region: ${CE_REGION}) ==="
    ibmcloud login --apikey "$QC_MASTER_API_KEY" -r "$CE_REGION" --quiet
    echo "Targeting resource group: ${CE_RESOURCE_GROUP_NAME}..."
    ibmcloud target -g "$CE_RESOURCE_GROUP_NAME" --quiet
    echo "Selecting CE project: ${CE_PROJECT_NAME}..."
    ibmcloud ce project select -n "$CE_PROJECT_NAME" --quiet
fi

echo ""
# Timing: T0 is the moment we submit the fleet-create (provisioning starts here).
T_SUBMIT=$(date +%s)
CREATE_OUT=$("${FLEET_CMD[@]}" 2>&1) || {
    echo "$CREATE_OUT"
    echo "FLEET_TIMING profile=${FLEET_PROFILE_LABEL} cpu=${FLEET_CPU} memory=${FLEET_MEMORY} gpu=${FLEET_GPU:-none} name=${FLEET_NAME} final_status=create_error provisioning_s=NA execution_s=NA total_s=NA"
    exit 1
}
echo "$CREATE_OUT"
echo ""
echo "=== Fleet '${FLEET_NAME}' submitted ==="

# --- Resolve the fleet id ---
# `fleet create` prints "... and ID '<uuid>'"; parse it. Fall back to the list.
FLEET_ID=$(printf '%s\n' "$CREATE_OUT" | sed -nE "s/.*ID '([0-9a-fA-F-]{36})'.*/\1/p" | head -1)
if [ -z "$FLEET_ID" ]; then
    for _ in $(seq 1 12); do
        FLEET_ID=$(ibmcloud ce fleet list --output json 2>/dev/null \
            | jq -r --arg n "$FLEET_NAME" '.fleets[]? | select(.name==$n) | .id' | head -1) || true
        if [ -n "$FLEET_ID" ] && [ "$FLEET_ID" != "null" ]; then break; fi
        sleep 5
    done
fi
if [ -z "$FLEET_ID" ] || [ "$FLEET_ID" = "null" ]; then
    echo "Error: could not resolve id for fleet '$FLEET_NAME'."
    echo "FLEET_TIMING profile=${FLEET_PROFILE_LABEL} cpu=${FLEET_CPU} memory=${FLEET_MEMORY} gpu=${FLEET_GPU:-none} name=${FLEET_NAME} final_status=no_id provisioning_s=NA execution_s=NA total_s=NA"
    exit 1
fi
echo "Fleet id: $FLEET_ID"

# --- Poll until the fleet reaches a terminal state ---
VERIFY_TIMEOUT="${VERIFY_TIMEOUT:-7200}"
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
        echo "  [+$(( $(date +%s) - T_SUBMIT ))s] status: ${STATUS:-<unknown>}"
        LAST_STATUS="$STATUS"
    fi
    case "$STATUS" in
        succeeded|successful|failed|canceled) break ;;
    esac
    sleep "$POLL_INTERVAL"
done
T_TERMINAL=$(date +%s)

# --- Timing from CE task timestamps (authoritative; not poll granularity) ---
# The fleet-level status is unreliable for the "running" edge (it can step from
# pending straight to successful), so we derive the intervals from the per-task
# timestamps CE records. NB the populated fields are created_at / started_at /
# finished_at — running_at / completed_at exist in the schema but stay null.
#   provisioning_s = started_at  - created_at   (created -> run)
#   execution_s    = finished_at - started_at   (run -> finished)
#   total_s        = finished_at - created_at
# The task (with its timestamps) persists in `fleet task list` after the fleet
# is terminal. Falls back to NA (and local wall-clock for total) if a timestamp
# is absent (e.g. the task failed before starting).
TASK_JSON_FILE="$(mktemp)"
ibmcloud ce fleet task list --fleet-id "$FLEET_ID" --output json > "$TASK_JSON_FILE" 2>/dev/null || echo '{}' > "$TASK_JSON_FILE"
TIMING_OUT=$(TASK_JSON_FILE="$TASK_JSON_FILE" python3 <<'PYEOF'
import os, json, datetime
try:
    with open(os.environ["TASK_JSON_FILE"]) as fh:
        data = json.load(fh)
except Exception:
    data = {}
tasks = data.get("tasks") or [{}]
t = tasks[0] if tasks else {}
def ep(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None
c = ep(t.get("created_at"))
r = ep(t.get("started_at") or t.get("running_at"))     # started_at is the populated one
f = ep(t.get("finished_at") or t.get("completed_at"))  # finished_at is the populated one
prov = str(int(round(r - c))) if (c is not None and r is not None) else "NA"
ex   = str(int(round(f - r))) if (r is not None and f is not None) else "NA"
tot  = str(int(round(f - c))) if (c is not None and f is not None) else "NA"
print(prov, ex, tot)
PYEOF
)
rm -f "$TASK_JSON_FILE"
read -r PROVISIONING_S EXECUTION_S TOTAL_S <<< "${TIMING_OUT:-NA NA NA}"
PROVISIONING_S="${PROVISIONING_S:-NA}"
EXECUTION_S="${EXECUTION_S:-NA}"
TOTAL_S="${TOTAL_S:-NA}"
# Fall back to local wall-clock for total if CE timestamps were unavailable.
[ "$TOTAL_S" = "NA" ] && TOTAL_S=$(( T_TERMINAL - T_SUBMIT ))

echo "FLEET_TIMING profile=${FLEET_PROFILE_LABEL} cpu=${FLEET_CPU} memory=${FLEET_MEMORY} gpu=${FLEET_GPU:-none} name=${FLEET_NAME} final_status=${STATUS:-unknown} provisioning_s=${PROVISIONING_S} execution_s=${EXECUTION_S} total_s=${TOTAL_S}"

# Report task-level detail on non-success (helps diagnose quota failures).
case "$STATUS" in
    succeeded|successful) ;;
    *)
        echo ""
        echo "Fleet did not succeed (last status: ${STATUS:-<unknown>})."
        ibmcloud ce fleet task list --fleet-id "$FLEET_ID" --output json 2>/dev/null \
            | jq -r '.tasks[]? | "  task \(.index): \(.status) — \(.status_details.reason // .status_details.result_code // "no detail")"' || true
        ;;
esac

# --- Optional COS result download (off by default) ---
if [ "${DOWNLOAD_RESULT:-0}" = "1" ]; then
    echo ""
    echo "=== Downloading result from COS ==="
    COS_ENDPOINT="${CE_COS_ENDPOINT:-https://s3.${CE_REGION}.cloud-object-storage.appdomain.cloud}"
    IAM_TOKEN=$(ibmcloud iam oauth-tokens --output json 2>/dev/null | jq -r '.iam_token') || true
    if [ -n "$IAM_TOKEN" ] && [ "$IAM_TOKEN" != "null" ]; then
        LOCAL_OUT="$(mktemp)"
        trap 'rm -f "$LOCAL_OUT"' EXIT
        for _ in $(seq 1 24); do
            if curl -fsS --max-time 20 -H "Authorization: $IAM_TOKEN" \
                    "${COS_ENDPOINT}/${CE_COS_BUCKET_USER_DATA_NAME}/${COS_RESULT_KEY}" \
                    -o "$LOCAL_OUT" 2>/dev/null && [ -s "$LOCAL_OUT" ]; then
                echo "Downloaded ($(wc -c < "$LOCAL_OUT" | tr -d ' ') bytes):"
                cat "$LOCAL_OUT"; echo ""
                break
            fi
            sleep 5
        done
    else
        echo "  (could not obtain IAM token; skipping download)"
    fi
fi

# --- Optional cleanup ---
if [ "${CLEANUP:-0}" = "1" ]; then
    echo ""
    echo "=== Deleting fleet (CLEANUP=1) ==="
    ibmcloud ce fleet delete --id "$FLEET_ID" --force --ignore-not-found \
        || echo "  (delete request returned non-zero; check: ibmcloud ce fleet get --id $FLEET_ID)"
else
    echo ""
    echo "Fleet kept. To remove it: ibmcloud ce fleet delete --id ${FLEET_ID} --force"
fi
