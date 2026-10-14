#!/bin/bash

# Baseline egress test for a Code Engine fleet (NO startup hooks).
#
# Runs a plain fleet task that probes TCP/TLS reachability to a set of hosts and
# writes a JSON report to the mounted COS path. Use it to learn what the fleet's
# private network can actually reach — e.g. is iam.cloud.ibm.com open while
# docker.io / quay.io / the public internet are blocked?
#
# It is a thin wrapper around create_ce_fleet.sh: it only sets FLEET_FUNCTION and
# FLEET_PYTHON_CODE, then hands off. All login / mount / COS-verify / cleanup
# behavior (and env vars like CLEANUP, VERIFY, VERIFY_TIMEOUT) come from there.
#
# This probes socket-level reachability (TCP connect + TLS handshake) of any
# host:port. To test whether an HTTPS *request* completes (e.g. behind the egress
# proxy, where every :443 connect is redirected), use test_fleet_https_egress.sh.
#
# Usage:
#   bash gateway/examples/test_fleet_egress.sh            # create, verify, keep
#   CLEANUP=1 bash gateway/examples/test_fleet_egress.sh  # delete fleet after
#   DRY_RUN=1 bash gateway/examples/test_fleet_egress.sh  # preview only
#
# Optional:
#   EGRESS_HOSTS   Space-separated host:port list to probe (default below)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Hosts to probe. iam.cloud.ibm.com is expected reachable (allowlisted); the
# *.icr.io and COS endpoints are positive controls (the image pull + COS mount
# already use them); docker.io / quay.io / example.com test general egress.
EGRESS_HOSTS="${EGRESS_HOSTS:-iam.cloud.ibm.com:443 private.icr.io:443 s3.us-east.cloud-object-storage.appdomain.cloud:443 registry-1.docker.io:443 quay.io:443 example.com:443}"

# Python probe (stdlib only). TCP-connect + best-effort TLS handshake per host,
# recording reachability, TLS version, error, and elapsed time. Writes the JSON
# report to /job_user_data/results.json (create_ce_fleet.sh's default mount path).
read -r -d '' PROBE <<PYEOF || true
import json, socket, ssl, time
hosts = []
for item in "${EGRESS_HOSTS}".split():
    host, _, port = item.partition(":")
    hosts.append((host, int(port or "443")))
results = {}
for host, port in hosts:
    entry = {"reachable": False}
    t0 = time.time()
    try:
        with socket.create_connection((host, port), timeout=10) as sock:
            try:
                ctx = ssl.create_default_context()
                with ctx.wrap_socket(sock, server_hostname=host) as ss:
                    entry["tls"] = ss.version()
            except Exception as e:
                entry["tls_error"] = str(e)
            entry["reachable"] = True
    except Exception as e:
        entry["error"] = str(e)
    entry["elapsed_s"] = round(time.time() - t0, 2)
    results[f"{host}:{port}"] = entry
    print(host, port, "->", entry)
open("/job_user_data/results.json", "w").write(json.dumps(results, indent=2))
print("WROTE /job_user_data/results.json")
PYEOF

export FLEET_FUNCTION="${FLEET_FUNCTION:-egress-test}"
export FLEET_PYTHON_CODE="$PROBE"

echo "=== Fleet egress test: probing ==="
echo "  $EGRESS_HOSTS"
echo ""

exec "$SCRIPT_DIR/create_ce_fleet.sh"
