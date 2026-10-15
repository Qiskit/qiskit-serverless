# Fleet compute-profile timing benchmark

Create Code Engine fleets across a set of compute profiles and measure their
lifecycle timings. This is the proxy-free sibling of
[`../fleet_egress_proxy`](../fleet_egress_proxy): no worker startup hook, no
privileged container — just fleet create + timing.

Resources are set with raw **`--cpu` / `--memory` / `--gpu`** values (NOT
`--worker-profile`). `--gpu` uses the CLI's `FAMILY:COUNT` form; run
`ibmcloud ce fleet worker profiles` to see the valid GPU families in your region.

## What it measures

Each fleet run records two intervals:

| Timing | Interval | Meaning |
|--------|----------|---------|
| `provisioning_s` | submit → `running` | worker provisioning (created → run) |
| `execution_s`    | `running` → terminal | task run (running → finished) |
| `total_s`        | submit → terminal | end to end |

Each profile is created `REPS` times (default 5) to capture variation, with a
`SLEEP_BETWEEN` pause (default 30s) between runs.

## Profiles

Mapped from the Qiskit Serverless compute-profile spec to raw CE resources.
GPU families adjusted to valid CE tokens (**L40 → `l40s`**, **A100 → `a100`**);
TB memory aligned to the matching worker profile.

| Class | Size | vCPU | Memory | GPU | `--cpu` | `--memory` | `--gpu` |
|-------|------|------|--------|-----|---------|-----------|---------|
| General | S | 8 | 32 GB | – | 8 | 32G | – |
| General | M | 16 | 128 GB | – | 16 | 128G | – |
| General | L | 48 | 768 GB | – | 48 | 768G | – |
| General | XL | 128 | 1.5 TB | – | 128 | 1536G | – |
| Performance | S | 24 | 120 GB | L40 | 24 | 120G | `l40s:1` |
| Performance | M | 20 | 320 GB | 2×A100 | 20 | 320G | `a100:2` |
| Performance | L | 80 | 1.2 TB | 8×A100 | 80 | 1280G | `a100:8` |

Notes:
- `performance-s` maps exactly to `gx3-24x120x1l40s`; `performance-l` to
  `gx2-80x1280x8a100` (1.2 TB → 1280 GiB).
- `general-l` (48×768), `general-xl` (128×1536) and `performance-m`
  (20×320×2a100) don't correspond to a single listed worker profile — the raw
  values are passed as-is; CE accepting or rejecting them is itself a datapoint.
- Large / GPU profiles may fail on account quota. That still produces a timing
  row (`final_status=failed`, provisioning up to the failure); the run continues.

Edit the `PROFILE_TABLE` at the top of `run_fleet_profiles.sh` to change any
value.

## Files

| File | Role |
|------|------|
| `run_fleet_profiles.sh` | Driver: loops profiles × `REPS`, logs in once, writes `results/timings_<ts>.csv`, prints a summary. |
| `create_ce_fleet.sh`    | Creates one fleet with given `--cpu/--memory/--gpu`, polls to terminal, emits the `FLEET_TIMING` line. |
| `setup_fleets_env.sh`   | Not present here — both scripts source [`../setup_fleets_env.sh`](../setup_fleets_env.sh). |

## Prerequisites
- `ibmcloud` CLI (code-engine plugin), `jq`, `python3`, `curl`, `uuidgen`
- `QC_MASTER_API_KEY` exported (your IBM Cloud API key)

## Run

```bash
# Quick smoke: 1 rep of two cheap profiles, delete after each
REPS=1 PROFILES="general-s general-m" CLEANUP=1 \
  bash gateway/examples/fleet_profiles/run_fleet_profiles.sh

# Full benchmark: all 7 profiles × 5 reps (long — many fleets, sequential)
CLEANUP=1 bash gateway/examples/fleet_profiles/run_fleet_profiles.sh

# Preview the commands without calling the cloud
DRY_RUN=1 bash gateway/examples/fleet_profiles/run_fleet_profiles.sh
```

### Driver env vars
| Var | Default | Meaning |
|-----|---------|---------|
| `REPS` | 5 | Repetitions per profile |
| `SLEEP_BETWEEN` | 30 | Seconds to sleep between runs |
| `PROFILES` | *(all)* | Space-separated subset of profile labels |
| `CLEANUP` | 1 | Delete each fleet once terminal |
| `FLEET_TASK_SLEEP` | 30 | Seconds the task sleeps while `running`, so `execution_s` is measurable |
| `DOWNLOAD_RESULT` | 0 | Also download+print each result from COS |
| `VERIFY_TIMEOUT` | 7200 | Per-fleet wait timeout (s) — large profiles can provision slowly |
| `POLL_INTERVAL` | 20 | Seconds between status polls |
| `DRY_RUN` | 0 | Print commands only |

## Output

`results/timings_<timestamp>.csv`:

```
profile,cpu,memory,gpu,rep,fleet_name,final_status,provisioning_s,execution_s,total_s
general-s,8,32G,none,1,fp-general-s-r1-ab12cd34,succeeded,312,47,359
...
```

and a summary table `results/summary_<timestamp>.txt` (also printed to the
console) with per-profile **min / avg / max / std** (sample std, n−1) of
`provisioning_s` and `execution_s`. NA rows (failed/error runs) are excluded
from the stats but listed under `statuses`.

> **Note on timing accuracy:** the fleet-level status is unreliable for the
> `running` edge (it can jump `pending → successful`), so timings come from the
> per-task timestamps CE records — **`created_at` / `started_at` / `finished_at`**
> from `ibmcloud ce fleet task list` (the `running_at` / `completed_at` fields
> exist but stay null). These are second-accurate and independent of the poll
> interval; `POLL_INTERVAL` only affects how quickly the script notices the
> terminal state.
