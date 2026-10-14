#!/bin/bash
#
# Mirror the proxy image (mitmproxy) from docker.io into the project's
# ICR namespace so a CE fleet worker — which cannot reach docker.io — can pull
# them. Run this ONCE from a machine that CAN reach docker.io (e.g. your laptop).
#
# Credentials for ICR are read from the Code Engine `icr-pull-secret` registry
# secret (server/username/password) and used only in-memory; they are never
# printed or written to disk.
#
# Prerequisites:
#   - podman installed locally, with docker.io reachable
#   - ibmcloud CLI logged in (ibmcloud login) and the code-engine project selected
#   - QC_MASTER_API_KEY exported (so we can resolve the CE project/secret)
#
# Usage:
#   bash gateway/examples/fleet_proxy_hook/mirror_proxy_images.sh

set -Eeuo pipefail

ICR_NAMESPACE="${ICR_NAMESPACE:-qc-qiskit-functions-ce-staging}"
PULL_SECRET_NAME="${PULL_SECRET_NAME:-icr-pull-secret}"
# Push from here via the PUBLIC ICR endpoint (icr.io). The icr-pull-secret's
# server is the PRIVATE endpoint (private.icr.io = 166.9.x.x), reachable only
# from inside IBM Cloud (the worker), NOT from this machine. Same registry/
# namespace/images — only the network path differs.
MIRROR_REGISTRY="${MIRROR_REGISTRY:-icr.io}"
# CE fleet workers are linux/amd64 — mirror that variant regardless of the host
# arch (e.g. an arm64 Mac), or the worker won't be able to run the image.
PLATFORM="${PLATFORM:-linux/amd64}"

# src docker.io ref | dest repo:tag (within the ICR namespace)
IMAGES=(
  "docker.io/mitmproxy/mitmproxy:latest|mitmproxy:latest"
)

command -v podman >/dev/null || { echo "Error: podman not found."; exit 1; }

echo "=== Reading ICR credentials from CE secret '${PULL_SECRET_NAME}' ==="
SECRET_JSON=$(ibmcloud ce secret get --name "$PULL_SECRET_NAME" --output json 2>/dev/null)
PRIVATE_SERVER=$(echo "$SECRET_JSON" | jq -r '.data.server')    # what the worker pulls from
ICR_USERNAME=$(echo "$SECRET_JSON"   | jq -r '.data.username')  # iamapikey
ICR_PASSWORD=$(echo "$SECRET_JSON"   | jq -r '.data.password')  # the apikey (works for icr.io too)
unset SECRET_JSON
if [ -z "$ICR_PASSWORD" ] || [ "$ICR_PASSWORD" = "null" ]; then
    echo "Error: could not read credentials from secret '${PULL_SECRET_NAME}'."
    exit 1
fi
echo "  push via ${MIRROR_REGISTRY} (public) as ${ICR_USERNAME}; worker pulls via ${PRIVATE_SERVER} (private)"

echo "=== Logging podman in to ${MIRROR_REGISTRY} ==="
printf '%s' "$ICR_PASSWORD" | podman login "$MIRROR_REGISTRY" -u "$ICR_USERNAME" --password-stdin
unset ICR_PASSWORD

for entry in "${IMAGES[@]}"; do
    SRC="${entry%%|*}"
    DEST_REPO="${entry##*|}"
    DEST="${MIRROR_REGISTRY}/${ICR_NAMESPACE}/${DEST_REPO}"
    echo ""
    echo "=== Mirroring ${SRC} (${PLATFORM})  ->  ${DEST} ==="
    podman pull --platform "$PLATFORM" "$SRC"
    podman tag  "$SRC" "$DEST"
    podman push "$DEST"
done

echo ""
echo "=== Done. Mirrored images (worker pulls via the PRIVATE endpoint): ==="
for entry in "${IMAGES[@]}"; do
    echo "  ${PRIVATE_SERVER}/${ICR_NAMESPACE}/${entry##*|}"
done
echo ""
echo "worker_proxy_hook.sh is already pointed at these private.icr.io paths."
