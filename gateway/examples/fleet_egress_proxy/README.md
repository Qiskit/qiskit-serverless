# Fleet worker egress proxy — self-contained test bundle

Everything needed to stand up and test a **domain allow/deny egress proxy** on a
Code Engine fleet worker, via the experimental `__CE_INTERNAL_HOOK_AFTER_STARTUP`
hook. Ad-hoc research tooling — the production implementation will live in the
gateway Python (`core/ibm_cloud/code_engine/fleets/`).

## What it does

A startup hook runs on the worker (root, podman) before the task, starts one
**mitmproxy** in transparent mode, and redirects the task's outbound 80/443
through it. A tiny addon enforces a domain allowlist by **SNI** (HTTPS, cleartext
in the ClientHello) / **Host** (HTTP), with **no decryption**:

```
task ──80/443──▶ iptables REDIRECT ──▶ mitmproxy ──▶ allowed domain (spliced, real cert)
                                                  └─▶ anything else  → killed
```

Allowed traffic is *spliced* (passed through untouched) so the task needs no CA
trust; denied traffic is killed. `upstream_cert=false` ensures the proxy never
even contacts a denied host.

## Files

| File | Role |
|------|------|
| `mirror_proxy_images.sh` | One-time: mirror the mitmproxy image docker.io → ICR (worker can't reach docker.io). |
| `worker_proxy_hook.sh`   | **The proxy.** Runs as the worker startup hook: mitmproxy + allow/deny addon + iptables redirect. This is the artifact to port to Python. |
| `run_fleet_with_proxy.sh`| Launches a fleet with the hook and probes allowed vs blocked URLs. |
| `create_ce_fleet.sh`     | Engine: creates the fleet, waits, downloads the result from COS, verifies, cleans up. |
| `test_fleet_https_egress.sh` | The probe task (HTTPS GET each URL → reached/reset). |
| `setup_fleets_env.sh`    | CE project/COS config (sourced by `create_ce_fleet.sh`). |

## Prerequisites
- `ibmcloud` CLI (code-engine plugin), `jq`, `python3`, `curl`, `uuidgen`, `podman`
- `QC_MASTER_API_KEY` exported

## Run

```bash
# 1) One-time: mirror the proxy image into ICR
bash mirror_proxy_images.sh

# 2) Launch a fleet behind the proxy, verify, and delete it
CLEANUP=1 bash run_fleet_with_proxy.sh
```

Expected result (downloaded from COS): the allowlisted host (default
`qiskit-serverless.quantum.ibm.com`) → `reached:true`; everything else →
`reached:false` (reset). The worker hook's own log is returned under `hook_log`.

## Tuning
- Allowlist: `ALLOW_DOMAINS` in `worker_proxy_hook.sh` (or `ALLOWED_URL=` for one run).
- Probe set: `BLOCKED_URLS=` / `URLS=`.
- `DRY_RUN=1` previews the fleet-create command without calling the cloud.

## Findings baked in (from bring-up)
- `mitmproxy --allow-hosts` only selects what to MITM (tunnels the rest) — it is
  NOT a filter; blocking is done by the addon's `tls_clienthello` splice +
  `request` kill.
- Redirect the full podman bridge `10.88.0.0/16`, not `/24`.
- The worker's podman is already authed to `private.icr.io` (no `podman login`).
- `--env-from-secret` values are not visible to the hook process.
