"""Percentiles and the numbers of a run, from the raw run files."""

import math
import statistics
from collections import defaultdict
from datetime import datetime

from .sysdig import SCRAPE_SECONDS

# the status check of a job, the call every user repeats
STATUS_PATH = "/api/v1/jobs/{id}/"
TERMINAL_EVENTS = ("SUCCEEDED", "FAILED", "STOPPED")
CREATE_FLEET = "POST /projects/{project_id}/fleets"


def percentile(values: list[float], fraction: float) -> float | None:
    """The value below which `fraction` of the values fall, by nearest rank."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def outlier_limit(values: list[float]) -> float | None:
    """The box-plot rule: a value above Q3 + 1.5 IQR is an outlier."""
    if len(values) < 4:
        return None
    q1, q3 = percentile(values, 0.25), percentile(values, 0.75)
    return q3 + 1.5 * (q3 - q1)


def outliers(rows: list[dict], key: str, top: int = 5) -> dict:
    """How many rows are outliers on `key`, the limit, and the `top` slowest of them."""
    values = [row[key] for row in rows if row.get(key) is not None]
    limit = outlier_limit(values)
    if limit is None:
        return {"count": 0, "of": len(values), "limit": None, "worst": []}
    slow = sorted(
        (row for row in rows if row.get(key) is not None and row[key] > limit), key=lambda row: row[key], reverse=True
    )
    return {"count": len(slow), "of": len(values), "limit": limit, "worst": slow[:top]}


def job_times(users: list[dict], jobs: list[dict]) -> list[dict]:
    """One row per job: when it was QUEUED, how long it was QUEUED and PENDING, and its real start."""
    by_id = {job["job_id"]: job for job in jobs}
    rows = []
    for user in users:
        job = by_id.get(user.get("job_id"))
        if not job:
            continue
        events = job["events"]
        queued_at, pending_at = _first(events, "QUEUED"), _first(events, "PENDING")
        running_at = _first(events, "RUNNING")
        ended = [t for t in (_first(events, s) for s in TERMINAL_EVENTS) if t]
        started = _ts(job["started_at"]) if job.get("started_at") else None
        rows.append(
            {
                "user": user["user"],
                "job_id": job["job_id"],
                "queued_at": queued_at,
                "started": started,
                "ended_at": min(ended) if ended else None,
                "queued_seconds": (pending_at - queued_at) if queued_at and pending_at else None,
                "pending_seconds": (running_at - pending_at) if pending_at and running_at else None,
                "start_delay_seconds": (started - pending_at) if started and pending_at else None,
            }
        )
    return rows


def summary(values: list[float]) -> dict:
    """The median as p50, p95 and p99 by nearest rank, mean and max of the values."""
    return {
        "n": len(values),
        "p50": statistics.median(values) if values else None,
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "mean": sum(values) / len(values) if values else None,
        "max": max(values, default=None),
    }


def _ts(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _first(events: list[dict], status: str) -> float | None:
    times = [_ts(e["created"]) for e in events if e.get("status") == status and e.get("created")]
    return min(times) if times else None


def calls_by_endpoint(calls: list[dict]) -> dict:
    """{"METHOD path": {"client": summary, "server": summary, "status": {code: n}}}."""
    out: dict = defaultdict(lambda: {"client": [], "server": [], "status": defaultdict(int)})
    for call in calls:
        entry = out[f"{call['method']} {call['path']}"]
        entry["client"].append(call["seconds"])
        if call.get("server_seconds") is not None:
            entry["server"].append(call["server_seconds"])
        entry["status"][str(call["status"] if call.get("status") is not None else call.get("error"))] += 1
    return {
        endpoint: {"client": summary(v["client"]), "server": summary(v["server"]), "status": dict(v["status"])}
        for endpoint, v in out.items()
    }


def job_numbers(users: list[dict], jobs: list[dict]) -> dict:
    """The job numbers of the run, from the gateway's events and the function's start line."""
    times = job_times(users, jobs)

    def column(key: str) -> list[float]:
        return [t[key] for t in times if t[key] is not None]

    first_queued, real_starts = column("queued_at"), column("started")
    finals: dict = defaultdict(int)
    results: dict = defaultdict(int)
    for user in users:
        finals[user.get("final_status") or ("error" if user.get("error") else "unknown")] += 1
        if user.get("result_ok") is not None:
            results["ok" if user["result_ok"] else "failed"] += 1
    job_errors = {job["job_id"]: job.get("error") for job in jobs}
    return {
        "users": len(users),
        "final": dict(finals),
        "result": dict(results),
        "queued_seconds": summary(column("queued_seconds")),
        "pending_seconds": summary(column("pending_seconds")),
        "real_start_delay_seconds": summary(column("start_delay_seconds")),
        "all_started_seconds": (max(real_starts) - min(first_queued)) if real_starts and first_queued else None,
        "started": len(real_starts),
        # None for an old run that did not record the failed status checks
        "failed_polls": (
            sum(len(u["poll_errors"]) for u in users if u.get("poll_errors"))
            if any("poll_errors" in u for u in users)
            else None
        ),
        "errors": [u["error"] for u in users if u.get("error")]
        + [job_errors[u["job_id"]] for u in users if job_errors.get(u.get("job_id"))],
    }


def longest_tick_gap(sysdig: dict, window_end: float | None = None) -> float | None:
    """The longest time between two scheduler ticks, or from the last tick to window_end."""
    ticks = sorted(
        {float(v) for r in sysdig.get("last_tick_timestamp", {}).get("result", []) for _, v in r.get("values", [])}
    )
    if window_end is not None and ticks:
        ticks.append(window_end)
    return max((b - a for a, b in zip(ticks, ticks[1:])), default=None)


def finite_points(values: list) -> list[tuple[float, float]]:
    """The (time, value) points of a Sysdig series, without NaN and the infinities."""
    return [(t, float(v)) for t, v in values if math.isfinite(float(v))]


def counter_totals(sysdig: dict, name: str, keys: tuple[str, ...]) -> dict:
    """{(label values...): total} of a ``read: last`` counter."""
    out = {}
    for result in sysdig.get(name, {}).get("result", []):
        if result.get("values"):
            out[tuple(result["metric"].get(k, "") for k in keys)] = float(result["values"][-1][1])
    return out


def release(sysdig: dict) -> str | None:
    """The gateway and scheduler image tags of the run window."""
    tags = {r["metric"].get("image_tag") for r in sysdig.get("images", {}).get("result", [])}
    tags.discard(None)
    return ",".join(sorted(tags)) or None


def create_fleet(sysdig: dict) -> dict:
    """The Code Engine create fleet calls: how many were ok, their mean seconds, and how many failed."""
    keys = ("endpoint", "status")
    counts = counter_totals(sysdig, "code_engine_calls", keys)
    sums = counter_totals(sysdig, "code_engine_call_seconds_sum", keys)
    ok, total = counts.get((CREATE_FLEET, "ok"), 0), sums.get((CREATE_FLEET, "ok"))
    return {
        "calls": round(ok),
        "mean_seconds": total / ok if ok >= 0.5 and total is not None else None,
        "failed": round(
            sum(n for (endpoint, status), n in counts.items() if endpoint == CREATE_FLEET and status != "ok")
        ),
    }


def database(sysdig: dict) -> dict:
    """{deployment: queries, queries per second, new connections, connection errors, mean and peak p95 query seconds}.

    The totals include the background loop of the scheduler and one scrape before and after the run.
    """
    keys = ("kube_deployment_name",)
    connections = counter_totals(sysdig, "db_new_connections", keys)
    errors = counter_totals(sysdig, "db_connection_errors", keys)
    sums, counts = counter_totals(sysdig, "db_query_seconds_sum", keys), counter_totals(sysdig, "db_query_count", keys)
    p95 = {
        r["metric"].get("kube_deployment_name", ""): max(
            (v for _, v in finite_points(r.get("values", []))), default=None
        )
        for r in sysdig.get("db_query_p95", {}).get("result", [])
    }
    clock = sysdig.get("_clock", {})
    # the counters read one scrape before the window start, see sysdig._total
    window = clock["window_end"] - clock["window_start"] + SCRAPE_SECONDS if clock else None
    return {
        name: {
            "queries": round(n),
            "queries_per_second": n / window if window else None,
            "new_connections": round(connections.get((name,), 0)),
            # a counter with labels has no series before its first error
            "connection_errors": round(errors.get((name,), 0)),
            "query_mean_seconds": sums[(name,)] / n if n >= 0.5 and (name,) in sums else None,
            "query_p95_seconds": p95.get(name),
        }
        for (name,), n in sorted(counts.items())
    }


def sysdig_max(sysdig: dict) -> dict:
    """{metric: {series label: its peak over the window, or its last value for a running total}}."""
    out = {}
    for name, entry in sysdig.items():
        if name.startswith("_"):
            continue
        series = {}
        for result in entry.get("result", []):
            label = ",".join(f"{k}={v}" for k, v in sorted(result["metric"].items())) or "all"
            values = [v for _, v in finite_points(result.get("values", []))]
            if values:
                # a running total counts only the run at the last step; earlier steps also reach back before it
                series[label] = values[-1] if entry.get("read") == "last" else max(values)
        out[name] = series if series else entry.get("error", "no data")
    return out


# the driver is suspect above these
CPU_LIMIT_PERCENT = 80
PAUSE_LIMIT_SECONDS = 2
POLL_LAG_LIMIT_SECONDS = 1
# how much later than planned the last submit may go
SUBMIT_LATE_LIMIT_SECONDS = 2


def _poll_lags(polls: list[dict], poll_seconds: float) -> list[float]:
    """How much later than poll_seconds each status call of one user started, after the previous one ended."""
    polls = sorted(polls, key=lambda c: c["start"])
    return [b["start"] - (a["start"] + a["seconds"]) - poll_seconds for a, b in zip(polls, polls[1:])]


# pylint: disable-next=too-many-locals
def driver_health(calls: list[dict], health: list[dict], poll_seconds: float, planned_submit_seconds: float) -> dict:
    """The driver's own numbers and a verdict: CPU, pauses, poll lag, submit spread, and client minus server time."""
    polls: dict = defaultdict(list)
    for call in calls:
        if call["method"] == "GET" and call["path"] == STATUS_PATH:
            polls[call["user"]].append(call)
    lags = [lag for user_polls in polls.values() for lag in _poll_lags(user_polls, poll_seconds)]
    runs = sorted(c["start"] for c in calls if c["path"] == "/api/v1/programs/run/")
    overhead: dict = defaultdict(list)
    for call in calls:
        if call.get("server_seconds") is not None:
            overhead[f"{call['method']} {call['path']}"].append(call["seconds"] - call["server_seconds"])
    entry = {
        "cpu_max_percent": max((h["cpu_percent"] for h in health), default=None),
        "longest_pause_seconds": max(
            [h["late_seconds"] for h in health] + [abs(h["drift_seconds"]) for h in health], default=None
        ),
        "poll_lag_p95_seconds": percentile(lags, 0.95),
        "submit_spread_seconds": (runs[-1] - runs[0]) if len(runs) > 1 else None,
        "planned_submit_seconds": planned_submit_seconds,
        "client_minus_server_p95": {k: percentile(v, 0.95) for k, v in sorted(overhead.items())},
    }
    problems = []
    if (entry["cpu_max_percent"] or 0) > CPU_LIMIT_PERCENT:
        problems.append(f"cpu {entry['cpu_max_percent']:.0f} % of 1 core")
    if (entry["longest_pause_seconds"] or 0) > PAUSE_LIMIT_SECONDS:
        problems.append(f"the driver paused {entry['longest_pause_seconds']:.1f} s")
    if (entry["poll_lag_p95_seconds"] or 0) > POLL_LAG_LIMIT_SECONDS:
        problems.append(f"poll lag p95 {entry['poll_lag_p95_seconds']:.1f} s")
    late = (entry["submit_spread_seconds"] or 0) - planned_submit_seconds
    if late > SUBMIT_LATE_LIMIT_SECONDS:
        problems.append(f"the submits took {late:.1f} s longer than the rate limit planned")
    entry["problems"] = problems
    return entry
