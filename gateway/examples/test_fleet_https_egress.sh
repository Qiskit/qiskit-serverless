#!/bin/bash

# HTTPS-egress probe over a list of URLs: reports which a fleet task can actually
# reach (completes a request) vs. is reset. Thin wrapper around create_ce_fleet.sh.
#
# Run it directly for a BASELINE (no proxy), or let run_fleet_with_proxy.sh set
# the proxy hook and hand off here — same probe both ways, so the results are
# directly comparable (before/after the egress proxy).
#
# For socket-level reachability of arbitrary host:port (incl. non-HTTP, and the
# "timed out" vs "network unreachable" distinction), use test_fleet_egress.sh
# instead — this one tests whether an HTTPS *request* completes.
#
# Usage:
#   URLS="https://a https://b ..." CLEANUP=1 bash gateway/examples/test_fleet_https_egress.sh
#
# Optional:
#   HOOK_LOG_PATH   If set, the task reads this file into the result (used by
#                   run_fleet_with_proxy.sh to surface the worker hook's log).

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

URLS="${URLS:-https://qiskit-serverless.quantum.ibm.com https://example.com}"

# Cert verification is disabled so the result reflects reachability/policy, not
# trust: an allowlisted host spliced by the proxy presents its real cert anyway;
# a denied host is reset before any response.
read -r -d '' PROBE <<PYEOF || true
import json, ssl, urllib.request, urllib.error
ctx = ssl._create_unverified_context()
res = {"probes": {}}
hook_log = "${HOOK_LOG_PATH:-}"
if hook_log:
    try:
        res["hook_log"] = open(hook_log).read()
    except Exception as e:
        res["hook_log_error"] = str(e)
for url in "${URLS}".split():
    try:
        r = urllib.request.urlopen(url, timeout=15, context=ctx)
        res["probes"][url] = {"reached": True, "status": getattr(r, "status", None)}
    except urllib.error.HTTPError as he:
        res["probes"][url] = {"reached": True, "status": he.code}   # an HTTP response IS reaching it
    except Exception as ex:
        res["probes"][url] = {"reached": False, "error": (type(ex).__name__ + ": " + str(ex))[:160]}
    print(url, "->", res["probes"][url])
open("/job_user_data/results.json", "w").write(json.dumps(res, indent=2))
print("WROTE /job_user_data/results.json")
PYEOF
export FLEET_PYTHON_CODE="$PROBE"
export FLEET_FUNCTION="${FLEET_FUNCTION:-https-egress-test}"

echo "=== HTTPS egress probe ==="
echo "  $URLS"
echo ""

exec "$SCRIPT_DIR/create_ce_fleet.sh"
