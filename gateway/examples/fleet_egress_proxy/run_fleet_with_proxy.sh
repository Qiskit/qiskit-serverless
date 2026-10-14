#!/bin/bash
#
# Launch a CE fleet whose worker runs the transparent domain allow/deny egress
# proxy (worker_proxy_hook.sh) as its AFTER-STARTUP hook, then probes a few URLs.
# If the proxy works, the allowlisted domain is reachable and everything else is
# reset by the proxy.
#
# Prerequisite: run mirror_proxy_images.sh ONCE so the mitmproxy image exists in
# ICR (the worker cannot reach docker.io; it pulls from private.icr.io).
#
# Probe note: a transparent proxy redirects every :443 connect locally, so a
# plain TCP-connect test would show all hosts "reachable". This probe does an
# HTTPS GET (cert verification disabled — allowed hosts are spliced through with
# their real cert, denied hosts are killed) and reports reached vs reset.
#
# Usage:
#   CLEANUP=1 bash gateway/examples/fleet_egress_proxy/run_fleet_with_proxy.sh
#   DRY_RUN=1 bash gateway/examples/fleet_egress_proxy/run_fleet_with_proxy.sh   # preview

set -e

# All scripts in this bundle live in the same folder.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Probe targets + allowlist (single source of truth) ---
# The allowlist enforced by the hook defaults to the HOST of ALLOWED_URL, so the
# policy we enforce always matches what we probe. Override the allowlist with
# ALLOW_DOMAINS (space-separated hosts) and the probe set with URLS / BLOCKED_URLS.
ALLOWED_URL="${ALLOWED_URL:-https://qiskit-serverless.quantum.ibm.com}"
BLOCKED_URLS="${BLOCKED_URLS:-https://grafana.quantum.ibm.com https://example.com}"
export URLS="${URLS:-$ALLOWED_URL $BLOCKED_URLS}"
ALLOW_DOMAINS="${ALLOW_DOMAINS:-$(printf '%s' "$ALLOWED_URL" | sed -E 's#^[a-z]+://##; s#[:/].*##')}"

# --- Hook + privileged + hostpath ---
# Template the hook's ALLOW_DOMAINS to match ALLOW_DOMAINS above (keep them in
# sync — the hook also has a sane standalone default).
HOOK_SRC="$(cat "$DIR/worker_proxy_hook.sh")"
FLEET_HOOK_AFTER_STARTUP="$(printf '%s' "$HOOK_SRC" | sed -E "s|^ALLOW_DOMAINS=.*|ALLOW_DOMAINS=\"${ALLOW_DOMAINS}\"|")"
export FLEET_HOOK_AFTER_STARTUP
export FLEET_HOOK_RETRY_LIMIT="${FLEET_HOOK_RETRY_LIMIT:-1}"
export FLEET_HOOK_MAX_EXEC_TIME="${FLEET_HOOK_MAX_EXEC_TIME:-15m}"  # image pull + setup
export FLEET_PRIVILEGED="${FLEET_PRIVILEGED:-true}"
export FLEET_FUNCTION="${FLEET_FUNCTION:-proxy-egress-test}"
# Mount the hook's workdir so the task can read its log — the only way to retrieve
# hook output after the fleet is deleted. The probe picks up HOOK_LOG_PATH.
export FLEET_HOSTPATH_MOUNTS="${FLEET_HOSTPATH_MOUNTS:-/tmp/ce-proxy:/ce-proxy}"
export HOOK_LOG_PATH="${HOOK_LOG_PATH:-/ce-proxy/hook.log}"

echo "=== Fleet with transparent egress proxy hook ==="
echo "  hook   : worker_proxy_hook.sh (mitmproxy + iptables, domain allow/deny)"
echo "  allow  : ${ALLOW_DOMAINS}"
echo "  expect : ${ALLOWED_URL} -> reached:true; others -> reached:false (reset)"
echo "  prereq : mirror_proxy_images.sh has populated ICR with the mitmproxy image."
echo ""

# Same probe as a bare baseline run — only difference is the proxy hook above.
exec "$DIR/test_fleet_https_egress.sh"
