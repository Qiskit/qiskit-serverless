#!/bin/bash
#
# Benchmark Code Engine fleet lifecycle timings across compute profiles.
#
# For each profile in the table below, create the fleet REPS times (default 5)
# to capture variation, sleeping SLEEP_BETWEEN seconds between runs. Each run
# records two timings via create_ce_fleet.sh:
#
#   provisioning_s = submit  -> running   (created -> run)
#   execution_s    = running -> terminal  (running -> finished)
#
# Resources are expressed as raw --cpu / --memory / --gpu values (NOT
# --worker-profile). GPU families use the CLI's FAMILY:COUNT form; see
# `ibmcloud ce fleet worker profiles` for valid families in the region.
#
# Results are appended to results/timings_<timestamp>.csv and summarised
# (min/avg/max per profile) at the end.
#
# Usage:
#   CLEANUP=1 bash gateway/examples/fleet_profiles/run_fleet_profiles.sh
#   REPS=1 PROFILES="general-s performance-s" bash .../run_fleet_profiles.sh   # quick smoke
#   DRY_RUN=1 bash .../run_fleet_profiles.sh                                    # preview only
#
# Env vars:
#   REPS            Repetitions per profile (default: 5)
#   SLEEP_BETWEEN   Seconds to sleep between runs (default: 30)
#   PROFILES        Space-separated subset of profile labels to run (default: all)
#   CLEANUP         1 = delete each fleet after it terminates (default: 1)
#   DOWNLOAD_RESULT 1 = also download+print each result from COS (default: 0)
#   VERIFY_TIMEOUT  Per-fleet wait timeout in seconds (default: 1800)
#   POLL_INTERVAL   Seconds between status polls (default: 20)
#   DRY_RUN         1 = print commands without calling the cloud (default: 0)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Profile table: "label|cpu|memory|gpu" (gpu empty = no GPU) --------------
# Mapped from the Qiskit Serverless compute-profile spec to raw CE resources.
# GPU families adjusted to valid CE tokens (L40 -> l40s, A100 -> a100); TB
# memory aligned to the matching worker profile (1.2 TB -> 1280G via
# gx2-80x1280x8a100, 1.5 TB -> 1536G). Edit freely — values are passed verbatim.
#
#   Class        Size  vCPU  Memory   GPU
#   General      S       8   32 GB    -
#   General      M      16   128 GB   -
#   General      L      48   768 GB   -
#   General      XL    128   1.5 TB   -
#   Performance  S      24   120 GB   L40   (l40s x1)
#   Performance  M      20   320 GB   A100  (a100 x2)
#   Performance  L      80   1.2 TB   A100  (a100 x8)
PROFILE_TABLE=(
    "general-s|8|32G|"
    "general-m|16|128G|"
    "general-l|48|768G|"
    "general-xl|128|1536G|"
    "performance-s|24|120G|l40s:1"
    "performance-m|20|320G|a100:2"
    "performance-l|80|1280G|a100:8"
)

REPS="${REPS:-5}"
SLEEP_BETWEEN="${SLEEP_BETWEEN:-30}"
CLEANUP="${CLEANUP:-1}"
DOWNLOAD_RESULT="${DOWNLOAD_RESULT:-0}"
FLEET_TASK_SLEEP="${FLEET_TASK_SLEEP:-30}"   # in-task sleep so execution_s is measurable
DRY_RUN="${DRY_RUN:-0}"

# --- Load shared config + resolve region/project for a single login ----------
echo "=== Loading Fleets configuration ==="
# shellcheck source=../setup_fleets_env.sh
source "$SCRIPT_DIR/../setup_fleets_env.sh"

PROJECT_JSON=$(echo "$CE_PROJECTS" | jq -r '.[0]')
CE_PROJECT_NAME=$(echo "$PROJECT_JSON" | jq -r '.project_name')
CE_REGION=$(echo "$PROJECT_JSON" | jq -r '.region')
CE_RESOURCE_GROUP_NAME="${CE_RESOURCE_GROUP_NAME:-qiskit-functions-ce-staging}"

# --- Output CSV --------------------------------------------------------------
RESULTS_DIR="$SCRIPT_DIR/results"
mkdir -p "$RESULTS_DIR"
STAMP=$(date +%Y%m%d-%H%M%S)
CSV="$RESULTS_DIR/timings_${STAMP}.csv"
echo "profile,cpu,memory,gpu,rep,fleet_name,final_status,provisioning_s,execution_s,total_s" > "$CSV"
echo "Writing results to: $CSV"

# --- Login once; children skip it via SKIP_LOGIN=1 --------------------------
if [ "$DRY_RUN" != "1" ]; then
    echo ""
    echo "=== Logging into IBM Cloud (region: ${CE_REGION}) ==="
    ibmcloud login --apikey "$QC_MASTER_API_KEY" -r "$CE_REGION" --quiet
    ibmcloud target -g "$CE_RESOURCE_GROUP_NAME" --quiet
    ibmcloud ce project select -n "$CE_PROJECT_NAME" --quiet
fi
export SKIP_LOGIN=1

# --- Select which profiles to run -------------------------------------------
# PROFILES (space-separated labels) narrows the set; empty = all.
run_this_profile() {
    local label="$1"
    [ -z "${PROFILES:-}" ] && return 0
    for want in $PROFILES; do
        [ "$want" = "$label" ] && return 0
    done
    return 1
}

# Extract "key=value" token from a FLEET_TIMING line.
timing_field() { printf '%s\n' "$1" | sed -nE "s/.*[[:space:]]$2=([^[:space:]]+).*/\1/p"; }

TOTAL_RUNS=0
for entry in "${PROFILE_TABLE[@]}"; do
    IFS='|' read -r label cpu memory gpu <<< "$entry"
    run_this_profile "$label" || continue

    for rep in $(seq 1 "$REPS"); do
        TOTAL_RUNS=$((TOTAL_RUNS + 1))
        fleet_name="fp-${label}-r${rep}-$(uuidgen | tr '[:upper:]' '[:lower:]' | cut -d- -f1)"
        echo ""
        echo "###########################################################"
        echo "# profile=${label} rep=${rep}/${REPS} cpu=${cpu} memory=${memory} gpu=${gpu:-none}"
        echo "# fleet=${fleet_name}"
        echo "###########################################################"

        # Run the single-fleet script, streaming its output to the console while
        # capturing it so we can parse the FLEET_TIMING line.
        RUN_LOG="$(mktemp)"
        set +e
        FLEET_PROFILE_LABEL="$label" \
        FLEET_CPU="$cpu" \
        FLEET_MEMORY="$memory" \
        FLEET_GPU="$gpu" \
        FLEET_NAME="$fleet_name" \
        FLEET_TASK_SLEEP="$FLEET_TASK_SLEEP" \
        CLEANUP="$CLEANUP" \
        DOWNLOAD_RESULT="$DOWNLOAD_RESULT" \
        DRY_RUN="$DRY_RUN" \
            bash "$SCRIPT_DIR/create_ce_fleet.sh" 2>&1 | tee "$RUN_LOG"
        set -e

        # Parse the (last) FLEET_TIMING line into a CSV row.
        timing_line=$(grep '^FLEET_TIMING' "$RUN_LOG" | tail -1)
        if [ -n "$timing_line" ]; then
            fstatus=$(timing_field "$timing_line" "final_status")
            prov=$(timing_field "$timing_line" "provisioning_s")
            exec_s=$(timing_field "$timing_line" "execution_s")
            total=$(timing_field "$timing_line" "total_s")
        else
            fstatus="no_timing"; prov="NA"; exec_s="NA"; total="NA"
        fi
        echo "${label},${cpu},${memory},${gpu:-none},${rep},${fleet_name},${fstatus},${prov},${exec_s},${total}" >> "$CSV"
        rm -f "$RUN_LOG"

        # Sleep between runs (skip after the very last run).
        if [ "$SLEEP_BETWEEN" -gt 0 ]; then
            echo "  ... sleeping ${SLEEP_BETWEEN}s before next run"
            sleep "$SLEEP_BETWEEN"
        fi
    done
done

# --- Summary -----------------------------------------------------------------
# Written to a file AND echoed. Per profile: count, ok count, and
# min / avg / max / std (sample std, n-1) for provisioning_s and execution_s.
# Only numeric rows count toward the stats; NA (failed/error) rows are excluded
# from the stats but still shown in the status list.
SUMMARY="$RESULTS_DIR/summary_${STAMP}.txt"
{
    echo "==========================================================="
    echo "  SUMMARY — ${TOTAL_RUNS} runs"
    echo "  per-run CSV: $CSV"
    echo "==========================================================="
    printf "%-15s %4s %3s | %-32s | %-32s | %s\n" \
        "profile" "reps" "ok" "provisioning_s min/avg/max/std" "execution_s min/avg/max/std" "statuses"
    awk -F',' 'NR>1 {
        p=$1; st=$7; prov=$8; ex=$9;
        if (!(p in reps)) { order[++nprof]=p }   # first-seen order (BSD awk: no asorti)
        reps[p]++;
        statuses[p]=statuses[p] (statuses[p]?",":"") st;
        if (prov ~ /^[0-9]+$/) { pc[p]++; if(pc[p]==1||prov<pmin[p])pmin[p]=prov; if(pc[p]==1||prov>pmax[p])pmax[p]=prov; psum[p]+=prov; psq[p]+=prov*prov }
        if (ex   ~ /^[0-9]+$/) { ec[p]++; if(ec[p]==1||ex<emin[p])emin[p]=ex; if(ec[p]==1||ex>emax[p])emax[p]=ex; esum[p]+=ex; esq[p]+=ex*ex }
    }
    function stat(n, sum, sq, mn, mx,   mean, var) {
        if (n < 1) return "-/-/-/-";
        mean = sum / n;
        var  = (n > 1) ? (sq - sum*sum/n) / (n - 1) : 0;
        if (var < 0) var = 0;   # guard tiny negative from float rounding
        return sprintf("%s/%.0f/%s/%.1f", mn, mean, mx, sqrt(var));
    }
    END {
        for (i=1;i<=nprof;i++) {
            p=order[i];
            pv = stat(pc[p], psum[p], psq[p], pmin[p], pmax[p]);
            ev = stat(ec[p], esum[p], esq[p], emin[p], emax[p]);
            printf "%-15s %4d %3d | %-32s | %-32s | %s\n", p, reps[p], (pc[p]?pc[p]:0), pv, ev, statuses[p];
        }
    }' "$CSV"
} | tee "$SUMMARY"

echo ""
echo "Done."
echo "  Per-run data : $CSV"
echo "  Summary table: $SUMMARY"
