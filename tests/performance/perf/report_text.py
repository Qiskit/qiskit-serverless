"""report.txt for one run, and the side by side table of several runs, built from the raw run files."""

from datetime import datetime, timezone
from functools import cached_property

from .logs import SUBMIT_PARTS, has_parts
from .run_dir import RunDir
from .stats import (
    STATUS_PATH,
    calls_by_endpoint,
    create_fleet,
    database,
    summary,
    driver_health,
    job_numbers,
    job_times,
    longest_tick_gap,
    outliers,
    release,
    sysdig_max,
)


def _s(value) -> str:
    return "-" if value is None else f"{value:.2f}"


def _ms(seconds: float | None) -> float | None:
    return None if seconds is None else seconds * 1000


def _summary(entry: dict) -> str:
    return f"n={entry['n']:<4} p50={_s(entry['p50']):>7} p95={_s(entry['p95']):>7} max={_s(entry['max']):>7}"


class Run:  # pylint: disable=too-many-instance-attributes
    """The raw files of one run, read once, and the numbers built from them, built once."""

    def __init__(self, run_dir: RunDir):
        self.meta = run_dir.read("meta.json")
        self.users = run_dir.read("users.jsonl")
        self.calls = run_dir.read("calls.jsonl")
        self.jobs = run_dir.read("jobs.jsonl")
        self.health = run_dir.read("health.jsonl")
        self.sysdig = run_dir.read("sysdig.json")
        self.submits = run_dir.read("submits.jsonl")
        self.status_calls = [c for c in self.calls if c["path"] == STATUS_PATH]

    @cached_property
    def job(self) -> dict:
        """The job numbers of the run."""
        return job_numbers(self.users, self.jobs)

    @cached_property
    def endpoints(self) -> dict:
        """The calls of the run by endpoint."""
        return calls_by_endpoint(self.calls)

    @cached_property
    def split(self) -> list[dict]:
        """The submits that have their parts."""
        return [s for s in self.submits if has_parts(s)]

    @cached_property
    def dist(self) -> dict:
        """Every time distribution of the run."""
        return distributions(self)

    def driver(self) -> dict:
        """The driver health numbers of the run."""
        return driver_health(
            self.calls, self.health, self.meta.get("poll_seconds", 5), self.meta.get("planned_submit_seconds", 0)
        )


def build(run_dir: RunDir) -> str:
    """The whole text report of one run."""
    run = Run(run_dir)
    meta = run.meta
    lines = [
        f"Run {meta['run_id']}  scenario={meta['scenario']}  gateway={meta['gateway']}",
        f"release={release(run.sysdig) or '-'}  driver git={meta['git_sha']}  client={meta['client_version']}",
        f"start={meta['start_utc']}  end={meta['end_utc']}",
    ]
    for section in (_jobs, _calls, _outliers, _driver, _database, _sysdig):
        lines += [""] + section(run)
    return "\n".join(lines) + "\n"


def _jobs(run: Run) -> list[str]:
    job = run.job
    failed = "not recorded" if job["failed_polls"] is None else job["failed_polls"]
    lines = [
        "== Jobs (seconds) ==",
        f"users={job['users']} final={job['final']} result={job['result']} failed status checks={failed}",
        f"  QUEUED        {_summary(job['queued_seconds'])}",
        f"  PENDING       {_summary(job['pending_seconds'])}",
        f"  real start    {_summary(job['real_start_delay_seconds'])}   (from PENDING to the perf-start line the "
        "function prints, so it includes the Code Engine fleet boot)",
        f"  all started   {_s(job['all_started_seconds'])}   ({job['started']} of {job['users']} started; "
        "from the first QUEUED to the last real start)",
    ]
    if run.submits:
        lines.append(
            f"  submit        {_summary(run.dist['submit s'])}   "
            f"(the whole scheduler submit, COS upload and create fleet, from its log line; {len(run.submits)} of "
            f"{len(run.jobs)} jobs, a failed submit has no log line)"
        )
        lines += _split(run.split, run.dist)
    else:
        lines.append("  submit        not collected (no submit lines from Cloud Logs)")
    fleet = create_fleet(run.sysdig)
    if fleet["calls"] or fleet["failed"]:
        lines.append(
            f"  create fleet  mean={_s(fleet['mean_seconds'])} s over {fleet['calls']} calls, {fleet['failed']} failed"
            "   (Code Engine HTTP call only, from the Sysdig counters, part of submit)"
        )
    lines += _not_done(run.users)
    lines += [f"  status check error x{n}: {message}" for message, n in _poll_errors(run.users)]
    counts: dict = {}
    for error in job["errors"]:
        counts[error] = counts.get(error, 0) + 1
    return lines + [f"  error x{n}: {error}" for error, n in sorted(counts.items(), key=lambda item: -item[1])[:5]]


def _split(split: list[dict], dist: dict) -> list[str]:
    """The p50 of each submit part, and the parts of the slowest submit."""
    if not split:
        return []

    def parts(value) -> str:
        return ", ".join(f"{_part(name)} {_s(value(name))}" for name in SUBMIT_PARTS)

    slowest = max(split, key=lambda s: s["seconds"])
    return [
        f"    split p50: {parts(lambda name: dist[f'submit {_part(name)} s']['p50'])}   (from the log timestamps, "
        f"{len(split)} jobs; the parts add up to submit for each job, not for the p50)",
        f"    slowest {_s(slowest['seconds'])}: {parts(lambda name: slowest[name])}",
    ]


def _part(name: str) -> str:
    return name.replace("_", " ")


def _not_done(users: list[dict]) -> list[str]:
    """One line per final status other than DONE, grouped by the last status before it and by the fleet."""
    groups: dict = {}
    for user in users:
        final = user.get("final_status") or ("error" if user.get("error") else "unknown")
        if final == "DONE":
            continue
        seen = [status.split(":")[0] for _, status in user.get("statuses") or []]
        before = [status for status in seen if status != final]
        # no status at all: the user failed before run() returned, so no job exists
        last = before[-1] if before else ("no job" if not user.get("job_id") else "nothing")
        key = (final, last, bool(user.get("fleet_id")))
        groups.setdefault(key, []).append(user["user"])
    lines = []
    for (final, last, fleet), ids in sorted(groups.items()):
        shown = ", ".join(str(i) for i in ids[:10]) + (", ..." if len(ids) > 10 else "")
        where = "before run(), no job" if last == "no job" else f"last {last}, {'had a fleet' if fleet else 'no fleet'}"
        lines.append(f"  {final} {len(ids)}: {where} (users {shown})")
    return lines


def _poll_errors(users: list[dict]) -> list[tuple[str, int]]:
    """The failed status check messages with their count, the most common first."""
    counts: dict = {}
    for user in users:
        for _, message in user.get("poll_errors") or []:
            counts[message] = counts.get(message, 0) + 1
    return sorted(counts.items(), key=lambda item: -item[1])[:5]


def _calls(run: Run) -> list[str]:
    lines = ["== Calls (seconds; client = laptop, server = Envoy's x-envoy-upstream-service-time) =="]
    for endpoint, entry in sorted(run.endpoints.items()):
        lines += [
            f"{endpoint}  status={entry['status']}",
            f"  client {_summary(entry['client'])}",
            f"  server {_summary(entry['server'])}",
        ]
    html = sum(1 for c in run.calls if c.get("html"))
    if html:
        lines.append(f"{html} error answers were HTML pages, so they came from Cloudflare and not the gateway")
    return lines


def _outliers(run: Run) -> list[str]:
    lines = ["== Outliers (above Q3 + 1.5 IQR, the 5 worst of each) =="]
    run_start = min((c["start"] for c in run.calls), default=0)
    by_endpoint: dict = {}
    for call in run.calls:
        by_endpoint.setdefault(f"{call['method']} {call['path']}", []).append(call)
    for endpoint, endpoint_calls in sorted(by_endpoint.items()):
        found = outliers(endpoint_calls, "seconds")
        if found["count"]:
            lines.append(f"{endpoint}: {found['count']} of {found['of']} above {_s(found['limit'])} s")
            lines += [
                f"  user {c.get('user')} at +{c['start'] - run_start:.0f} s: {c['seconds']:.2f} s, "
                f"server {_s(c.get('server_seconds'))} s, status {c.get('status')}"
                for c in found["worst"]
            ]
    times = job_times(run.users, run.jobs)
    for key, label in (("queued_seconds", "time in QUEUED"), ("start_delay_seconds", "real start delay")):
        found = outliers(times, key)
        if found["count"]:
            lines.append(f"{label}: {found['count']} of {found['of']} jobs above {_s(found['limit'])} s")
            lines += [f"  user {t['user']} job {t['job_id'][:8]}: {t[key]:.1f} s" for t in found["worst"]]
    return lines


def _driver(run: Run) -> list[str]:
    entry = run.driver()
    lines = [
        "== Driver health (is the driver the bottleneck?) ==",
        f"cpu max {_s(entry['cpu_max_percent'])} % of 1 core, longest pause {_s(entry['longest_pause_seconds'])} s, "
        f"poll lag p95 {_s(entry['poll_lag_p95_seconds'])} s, submits spread over "
        f"{_s(entry['submit_spread_seconds'])} s (planned {_s(entry['planned_submit_seconds'])} s)",
    ]
    lines += [f"  client - server p95: {k} {_s(v)} s" for k, v in entry["client_minus_server_p95"].items()]
    lines.append(
        "  driver may be the bottleneck: " + ", ".join(entry["problems"]) if entry["problems"] else "  driver OK"
    )
    if not run.health:
        lines.append("no health.jsonl, so no driver CPU and pause numbers")
    return lines


def _database(run: Run) -> list[str]:
    lines = [
        "== Database (Django; the totals include the scheduler background loop and one scrape before and after "
        "the run) =="
    ]
    found = database(run.sysdig)
    if not found:
        return lines + ["not collected"]
    for name, entry in found.items():
        lines.append(
            f"{name}: {entry['queries']} queries ({_s(entry['queries_per_second'])}/s), "
            f"{entry['new_connections']} new connections, {entry['connection_errors']} connection errors, "
            f"query mean {_s(_ms(entry['query_mean_seconds']))} ms, p95 peak {_s(_ms(entry['query_p95_seconds']))} ms"
        )
    return lines


def _sysdig(run: Run) -> list[str]:
    lines = ["== Sysdig over the run window =="]
    if not run.sysdig:
        return lines + ["not collected"]
    clock = run.sysdig.get("_clock", {})
    if clock:
        lines.append(
            f"Sysdig clock {clock['offset_seconds']:+.2f} s from the driver, window "
            f"{datetime.fromtimestamp(clock['window_start'], timezone.utc):%H:%M:%S} to "
            f"{datetime.fromtimestamp(clock['window_end'], timezone.utc):%H:%M:%S} UTC"
        )
    gap = longest_tick_gap(run.sysdig, clock.get("window_end"))
    lines.append(f"longest gap between scheduler ticks: {_s(gap)} s (Sysdig keeps one tick a minute, so 60 means none)")
    for name, series in sysdig_max(run.sysdig).items():
        # the buckets and the database have their own lines, and the p50 and p99 series are for the dashboard
        if name == "last_tick_timestamp" or name.startswith("db_") or name.endswith(("_buckets", "_p50", "_p99")):
            continue
        if isinstance(series, str):
            lines.append(f"{name}: {series}")
            continue
        kind = "total" if run.sysdig[name].get("read") == "last" else "peak"
        lines.append(f"{name} ({kind}):")
        lines += [f"  {label}: {value:.2f}" for label, value in sorted(series.items())]
    return lines


def distributions(run: Run) -> dict:
    """{"<name> s": summary} of every time distribution of the run. row() shows some of them as "<name> p95 s".

    Read it as run.dist, so it is built once.
    """

    def server(endpoint: str) -> dict:
        return run.endpoints.get(endpoint, {}).get("server") or summary([])

    return {
        "QUEUED s": run.job["queued_seconds"],
        "real start s": run.job["real_start_delay_seconds"],
        "submit s": summary([s["seconds"] for s in run.submits]),
        **{f"submit {_part(name)} s": summary([s[name] for s in run.split]) for name in SUBMIT_PARTS},
        "sign-in server s": server("GET /api/v1/programs/"),
        "upload server s": server("POST /api/v1/programs/upload/"),
        "run server s": server("POST /api/v1/programs/run/"),
        "status server s": server(f"GET {STATUS_PATH}"),
    }


def row(run: Run) -> dict:
    """The numbers of one run that the side by side table shows."""
    job, dist = run.job, run.dist
    db = database(run.sysdig)
    driver = run.driver()
    errors = sum(1 for c in run.calls if (c.get("status") or 0) >= 500 or c.get("error"))
    machine = sysdig_max(run.sysdig)

    def worst(metric: str, container: str) -> float | None:
        series = machine.get(metric)
        if not isinstance(series, dict):
            return None
        values = [v for label, v in series.items() if f"container_name={container}," in label]
        return max(values, default=None)

    found = outliers(run.status_calls, "seconds")
    return {
        "users": job["users"],
        "sent at once": run.meta.get("burst"),
        "submits spread s": run.meta.get("planned_submit_seconds"),
        "DONE": job["final"].get("DONE", 0),
        "5xx or no answer": errors,
        "QUEUED p95 s": dist["QUEUED s"]["p95"],
        "real start p95 s": dist["real start s"]["p95"],
        "all started s": job["all_started_seconds"],
        "submit p95 s": dist["submit s"]["p95"],
        "create fleet mean s": create_fleet(run.sysdig)["mean_seconds"],
        "sign-in server p95 s": dist["sign-in server s"]["p95"],
        "upload server p95 s": dist["upload server s"]["p95"],
        "run server p95 s": dist["run server s"]["p95"],
        "status server p95 s": dist["status server s"]["p95"],
        "status outliers": f"{found['count']} of {found['of']}",
        "slowest status check client s": found["worst"][0]["seconds"] if found["worst"] else None,
        "gateway cpu max % of quota": worst("cpu_quota_used_percent", "gateway"),
        "scheduler memory max % of limit": worst("memory_limit_used_percent", "gateway-scheduler"),
        "scheduler db query mean ms": _ms(db.get("scheduler", {}).get("query_mean_seconds")),
        "scheduler db new connections": db.get("scheduler", {}).get("new_connections"),
        "driver cpu max % of 1 core": driver["cpu_max_percent"],
        "driver": "OK" if not driver["problems"] else "suspect",
    }


def compare(run_dirs: list[RunDir]) -> str:
    """One row per number and one column per run, so the runs read side by side."""
    runs = [Run(run_dir) for run_dir in run_dirs]
    rows = [row(run) for run in runs]
    names = [run_dir.name for run_dir in run_dirs]
    width = max(len(n) for n in names + ["number"]) + 2
    label = max(len(k) for k in rows[0]) + 2

    def cell(value) -> str:
        return _s(value) if isinstance(value, float) or value is None else str(value)

    lines = ["".ljust(label) + "".join(n.rjust(width) for n in names)]
    lines.append("scenario".ljust(label) + "".join(run.meta["scenario"].rjust(width) for run in runs))
    lines.append("release".ljust(label) + "".join((release(run.sysdig) or "-").rjust(width) for run in runs))
    for key in rows[0]:
        lines.append(key.ljust(label) + "".join(cell(r[key]).rjust(width) for r in rows))
    return "\n".join(lines) + "\n"
