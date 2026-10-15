#!/bin/bash

# Minimal worker startup-hook smoke test for Code Engine fleets.
#
# Proves the experimental __CE_INTERNAL_HOOK_AFTER_STARTUP mechanism actually
# runs on the worker BEFORE the task, WITHOUT needing any external egress:
#
#   1. The after-startup hook writes a marker file to a host path
#      (/tmp/ce_hook_marker/hook.txt) on the worker.
#   2. That host path is mounted into the task container at /hook_share via
#      __CE_INTERNAL_HOSTPATH_MOUNTS.
#   3. The task reads /hook_share/hook.txt and embeds it in results.json.
#   4. create_ce_fleet.sh downloads results.json from COS so we can confirm the
#      hook output reached the task.
#
# If the marker is present in the result, hooks work here. If not, the result
# still records what /hook_share contained, so we learn the hook's fs context.
#
# Thin wrapper around create_ce_fleet.sh; uses the private ICR python image
# (no docker.io pull). CLEANUP / VERIFY / DRY_RUN etc. pass through.
#
# Usage:
#   CLEANUP=1 bash gateway/examples/test_fleet_hook.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

HOST_MARKER_DIR="/tmp/ce_hook_marker"
CONTAINER_SHARE="/hook_share"

# After-startup hook (runs on the worker host). 'HOOKEOF' is quoted so the
# command substitutions run on the worker, not locally.
read -r -d '' HOOK <<'HOOKEOF' || true
#!/bin/bash
set -e
mkdir -p /tmp/ce_hook_marker
echo "hook ran on host=$(hostname) at $(date -u +%Y-%m-%dT%H:%M:%SZ)" > /tmp/ce_hook_marker/hook.txt
echo "after-startup hook wrote /tmp/ce_hook_marker/hook.txt"
HOOKEOF

# Task: read the marker the hook wrote and record it (plus a listing) into the
# result, so the object is always non-empty regardless of whether the hook fired.
read -r -d '' PROBE <<PYEOF || true
import json, os
p = "${CONTAINER_SHARE}/hook.txt"
res = {"marker_path": p, "marker_exists": os.path.exists(p)}
try:
    res["marker_content"] = open(p).read().strip()
except Exception as e:
    res["read_error"] = str(e)
try:
    res["share_listing"] = sorted(os.listdir("${CONTAINER_SHARE}"))
except Exception as e:
    res["listing_error"] = str(e)
print(res)
open("/job_user_data/results.json", "w").write(json.dumps(res, indent=2))
print("WROTE /job_user_data/results.json")
PYEOF

export FLEET_FUNCTION="${FLEET_FUNCTION:-hook-test}"
export FLEET_PYTHON_CODE="$PROBE"
export FLEET_HOOK_AFTER_STARTUP="$HOOK"
export FLEET_HOOK_RETRY_LIMIT="${FLEET_HOOK_RETRY_LIMIT:-1}"
export FLEET_HOOK_MAX_EXEC_TIME="${FLEET_HOOK_MAX_EXEC_TIME:-5m}"
export FLEET_HOSTPATH_MOUNTS="${FLEET_HOSTPATH_MOUNTS:-${HOST_MARKER_DIR}:${CONTAINER_SHARE}}"
export FLEET_PRIVILEGED="${FLEET_PRIVILEGED:-true}"

echo "=== Fleet hook smoke test ==="
echo "  hook writes : ${HOST_MARKER_DIR}/hook.txt (on worker)"
echo "  mounted into: ${CONTAINER_SHARE} (task container)"
echo ""

exec "$SCRIPT_DIR/create_ce_fleet.sh"
