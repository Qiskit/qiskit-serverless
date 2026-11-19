"""summary.json of one run, for the results dashboard: the compare numbers, the job timeline and the Sysdig series."""

import json
from pathlib import Path

from . import report_text
from .logs import SUBMIT_PARTS
from .report_text import Run, row
from .run_dir import RunDir
from .stats import counter_totals, finite_points, job_times, release

# Sysdig series kept for the charts. The others stay in sysdig.json only.
SERIES = [
    "cpu_quota_used_percent",
    "memory_limit_used_percent",
    "loop_duration_seconds_mean",
    "loop_duration_max",
    "task_duration_max",
    "scheduler_threads",
    # the page picks p50, p95 or p99 of these
    *(
        f"{name}_{stat}"
        for name in ("task_duration", "code_engine_call", "cos_call", "operation")
        for stat in ("p50", "p95", "p99")
    ),
]


def _shares(sysdig: dict) -> dict:
    """{(service, call, status): [[bucket edge s, share of calls under it], ...]}. Code Engine has ok calls only."""
    counts: dict = {}
    for (endpoint, edge), n in counter_totals(sysdig, "code_engine_call_buckets", ("endpoint", "le")).items():
        counts.setdefault(("Code Engine", endpoint, "ok"), {})[edge] = n
    for (operation, status, edge), n in counter_totals(
        sysdig, "cos_call_buckets", ("operation", "status", "le")
    ).items():
        counts.setdefault(("COS", operation, status), {})[edge] = n
    out = {}
    for key, edges in counts.items():
        total = edges.pop("+Inf", 0)
        if total >= 0.5:
            # not rounded, so a share just under a quantile never reads as over it
            out[key] = [[float(edge), n / total] for edge, n in sorted(edges.items(), key=lambda e: float(e[0]))]
    return out


def _cloud_calls(sysdig: dict) -> list[dict]:
    """One row per Code Engine endpoint or COS operation and status: calls, mean seconds, and the share of calls under
    each bucket edge. From the counters, so it is the HTTP call only. The shares are exact at the edges."""
    rows = []
    shares = _shares(sysdig)
    for service, calls, total, label in (
        ("Code Engine", "code_engine_calls", "code_engine_call_seconds_sum", "endpoint"),
        ("COS", "cos_calls", "cos_call_seconds_sum", "operation"),
    ):
        counts = counter_totals(sysdig, calls, (label, "status"))
        sums = counter_totals(sysdig, total, (label, "status"))
        for (name, status), n in sorted(counts.items()):
            if n < 0.5:
                continue
            entry = {"service": service, "call": name, "status": status, "calls": round(n), "mean_seconds": None}
            if (name, status) in sums:
                entry["mean_seconds"] = round(sums[(name, status)] / n, 3)
            if under := shares.get((service, name, status)):
                entry["under"] = under
            rows.append(entry)
    return rows


def _series(sysdig: dict, start: float) -> dict:
    """{metric: [{"labels": "...", "points": [[seconds from start, value], ...]}]}, NaN and infinite points dropped."""
    # the points are in the Sysdig clock, and start is in the driver's
    start += sysdig.get("_clock", {}).get("offset_seconds", 0)
    out = {}
    for name in SERIES:
        lines = []
        for result in sysdig.get(name, {}).get("result", []):
            points = [[round(t - start, 1), v] for t, v in finite_points(result.get("values", []))]
            if points:
                labels = ",".join(f"{k}={v}" for k, v in sorted(result["metric"].items()))
                lines.append({"labels": labels, "points": points})
        if lines:
            out[name] = lines
    return out


def summary(run_dir: RunDir) -> dict:
    """The small, shareable part of a run. The raw calls and job events stay in the run directory."""
    run = Run(run_dir)
    start = min((c["start"] for c in run.calls), default=0)
    times = job_times(run.users, run.jobs)
    first = min((t["queued_at"] for t in times if t["queued_at"]), default=0)
    finals = {u["user"]: u.get("final_status") for u in run.users}
    submits = {s["job_id"]: s for s in run.submits}
    return {
        "meta": {**run.meta, "release": release(run.sysdig)},
        "numbers": row(run),
        "dist": {name: {key: e[key] for key in ("p50", "p95", "p99", "mean", "n")} for name, e in run.dist.items()},
        "endpoints": {
            name: {"status": e["status"], "client": e["client"], "server": e["server"]}
            for name, e in run.endpoints.items()
        },
        "jobs": [
            {
                "user": t["user"],
                "job_id": t["job_id"][:8],
                "queued_at": round(t["queued_at"] - first, 1) if t["queued_at"] else None,
                "queued_seconds": t["queued_seconds"],
                "start_delay_seconds": t["start_delay_seconds"],
                "submit_seconds": s.get("seconds"),
                **{name: s.get(name) for name in SUBMIT_PARTS},
                "end_seconds": round(t["ended_at"] - first, 1) if t["ended_at"] else None,
                "final": finals.get(t["user"]),
            }
            for t in times
            for s in (submits.get(t["job_id"], {}),)
        ],
        "status_points": [[round(c["start"] - start, 1), c.get("server_seconds")] for c in run.status_calls],
        "cloud_calls": _cloud_calls(run.sysdig),
        "sysdig_queries": {
            k: run.sysdig[k]["query"]
            for k in SERIES
            if isinstance(run.sysdig.get(k), dict) and "query" in run.sysdig[k]
        },
        "sysdig_series": _series(run.sysdig, start),
    }


def exported(results: Path) -> set[str]:
    """The run ids already in the results repo."""
    return {path.parent.name for path in (results / "runs").glob("*/summary.json")}


def export(run_dirs: list[RunDir], results: Path) -> list[Path]:
    """Write runs/<run id>/summary.json and a fresh report.txt into the results repo, and rebuild runs/index.json."""
    written = []
    for run_dir in run_dirs:
        target = results / "runs" / run_dir.name
        target.mkdir(parents=True, exist_ok=True)
        (target / "summary.json").write_text(json.dumps(summary(run_dir), indent=1, allow_nan=False))
        report = report_text.build(run_dir)
        run_dir.write("report.txt", report)
        (target / "report.txt").write_text(report)
        written.append(target)
    write_index(results)
    return written


def write_index(results: Path) -> None:
    """runs/index.json, rebuilt from every runs/*/summary.json."""
    index = []
    for path in sorted((results / "runs").glob("*/summary.json")):
        data = json.loads(path.read_text())
        meta = data["meta"]
        index.append(
            {
                **{
                    k: meta.get(k)
                    for k in ("run_id", "scenario", "gateway", "start_utc", "release", "git_sha", "qps", "burst")
                },
                "numbers": data["numbers"],
            }
        )
    (results / "runs" / "index.json").write_text(json.dumps(index, indent=1))
