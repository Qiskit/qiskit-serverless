#!/bin/bash
#
# CE fleet worker AFTER-STARTUP hook: transparent domain allow/deny egress proxy.
#
# Pass this verbatim as __CE_INTERNAL_HOOK_AFTER_STARTUP. It runs on the worker
# host (root, podman available) BEFORE the task starts. It runs a single
# mitmproxy in transparent mode and redirects the task's outbound 80/443 through
# it. A small addon enforces a DOMAIN allowlist:
#   - allowed host -> spliced (passed through undecrypted; real cert, no CA needed)
#   - any other    -> connection killed
#
# Domain-level only: no decryption, no certificate management. HTTPS is filtered
# by the SNI in the TLS ClientHello (cleartext), HTTP by the Host header.
#
# Validated on a CE worker: allowed host reachable, others reset.
# Prereq: run mirror_proxy_images.sh once so MITM_IMAGE exists in ICR (the
# worker cannot reach docker.io; its podman is already authed to private.icr.io).

set -uo pipefail   # NOT -e: log every step even if one fails

### ===== Tunables =====
# Space-separated domains the task may reach. Everything else is blocked.
ALLOW_DOMAINS="qiskit-serverless.quantum.ibm.com"
# podman's DEFAULT bridge is 10.88.0.0/16 — use the full /16, not /24. A task can
# get any 10.88.x.y address; a /24 only catches 10.88.0.x and silently lets every
# other task bypass the proxy. (Confirmed by Marcelo/boewing testing.)
SUBNET_CIDR="10.88.0.0/16"
MITM_IMAGE="private.icr.io/qc-qiskit-functions-ce-staging/mitmproxy:latest"
MITM_PORT="8080"
WORKDIR="/tmp/ce-proxy"

mkdir -p "${WORKDIR}"
# Log to the hostpath so it can be inspected after the fleet is gone.
exec >> "${WORKDIR}/hook.log" 2>&1
echo "===== hook start $(date -u +%FT%TZ) on $(hostname) ====="
echo "podman: $(command -v podman 2>&1); allow: ${ALLOW_DOMAINS}"

# mitmproxy addon: allow/deny by domain, no decryption of allowed traffic.
cat > "${WORKDIR}/filter.py" <<PYEOF
from mitmproxy import http, tls
ALLOWED = set("${ALLOW_DOMAINS}".split())
def tls_clienthello(data: tls.ClientHelloData):
    if (data.client_hello.sni or "") in ALLOWED:
        data.ignore_connection = True      # HTTPS allowed -> passthrough (no MITM/CA)
def request(flow: http.HTTPFlow):
    if flow.request.pretty_host not in ALLOWED:  # denied HTTPS (post-MITM) or any HTTP
        flow.kill()
PYEOF

echo "==> Starting mitmproxy (transparent :${MITM_PORT})"
podman rm -f egress-proxy >/dev/null 2>&1 || true
podman run -d --name egress-proxy --network host \
  -v "${WORKDIR}/filter.py:/filter.py:ro,Z" \
  "${MITM_IMAGE}" \
  mitmdump --mode transparent --showhost \
    --listen-host 0.0.0.0 --listen-port "${MITM_PORT}" \
    --set block_global=false \
    --set upstream_cert=false \
    -s /filter.py

# Wait until mitmproxy is actually accepting before redirecting traffic to it,
# otherwise a task connection in the start-up gap hits a closed port (RST). Best
# effort: fall through after 30s (the redirect then fails closed, which is safe).
echo "==> Waiting for mitmproxy to accept on :${MITM_PORT}"
for _ in $(seq 1 30); do
  (exec 3<>"/dev/tcp/127.0.0.1/${MITM_PORT}") 2>/dev/null && { echo "    listening"; break; }
  sleep 1
done

echo "==> Enabling IPv4 forwarding"
sysctl -w net.ipv4.ip_forward=1 >/dev/null

echo "==> Installing iptables transparent-redirect rules"
iptables -t nat -N CE_PROXY 2>/dev/null || true
iptables -t nat -F CE_PROXY
# Don't proxy loopback / private destinations (the proxy itself, worker services).
iptables -t nat -A CE_PROXY -d 127.0.0.0/8    -j RETURN
iptables -t nat -A CE_PROXY -d 10.0.0.0/8     -j RETURN
iptables -t nat -A CE_PROXY -d 172.16.0.0/12  -j RETURN
iptables -t nat -A CE_PROXY -d 192.168.0.0/16 -j RETURN
# Redirect the task's HTTP and HTTPS out through mitmproxy.
iptables -t nat -A CE_PROXY -p tcp --dport 80  -j REDIRECT --to-ports "${MITM_PORT}"
iptables -t nat -A CE_PROXY -p tcp --dport 443 -j REDIRECT --to-ports "${MITM_PORT}"
iptables -t nat -C PREROUTING -s "${SUBNET_CIDR}" -p tcp -j CE_PROXY 2>/dev/null || \
iptables -t nat -A PREROUTING -s "${SUBNET_CIDR}" -p tcp -j CE_PROXY

echo "--- nat table ---"; iptables -t nat -S 2>&1 || true
echo "--- containers ---"; podman ps 2>&1 || true
echo "==> Proxy hook complete. Egress restricted to: ${ALLOW_DOMAINS}"
echo "===== hook end $(date -u +%FT%TZ) ====="
