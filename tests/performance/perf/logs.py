"""The scheduler log lines of a run, from IBM Cloud Logs: the time of each whole submit, split into its steps."""

import json
import re
import urllib.request
from datetime import datetime, timezone

from . import iam
from .config import CloudLogs

# FleetsJobSubmitter.submit logs the last line once a job reached PENDING (gateway/scheduler/schedule.py). The other
# three come from FleetsRunner.submit, in this order, so the gaps between them split the submit into its steps.
SUBMIT_LINE = re.compile(r"job_id=([0-9a-f-]+) Execute job \(([0-9.]+)s\)")
STEP_LINES = {
    "uploaded": re.compile(r"COS configured for job_id \[([0-9a-f-]+)\]"),
    "creating": re.compile(r"Submitting job_id=\[([0-9a-f-]+)\]"),
    "created": re.compile(r"Submitted job_id=\[([0-9a-f-]+)\]"),
}
# a job can reach PENDING a few ticks after the run end. The query sees those lines only because the Sysdig wait runs
# first
MARGIN_SECONDS = 120
QUERY_LIMIT = 5000
# the parts of a submit, in the order they happen
SUBMIT_PARTS = ("cos_upload", "prepare", "create_fleet", "save")


def has_parts(submit: dict) -> bool:
    """True when the submit is split into its parts. One with a missing log line has only seconds."""
    return all(name in submit for name in SUBMIT_PARTS)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _query(cloud_logs: CloudLogs, token: str, query: str, start: float, end: float) -> list[tuple[float, str]]:
    """(epoch seconds, message) of every matching log line. The API answers with server-sent events."""
    body = {
        "query": query,
        "metadata": {
            "tier": "frequent_search",
            "syntax": "dataprime",
            "start_date": _iso(start),
            "end_date": _iso(end),
            "limit": QUERY_LIMIT,
        },
    }
    request = urllib.request.Request(
        f"https://{cloud_logs.instance_id}.api.{cloud_logs.region}.logs.cloud.ibm.com/v1/query",
        data=json.dumps(body).encode(),
        method="POST",
        # without a User-Agent the WAF answers 403 with an HTML page
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "qiskit-serverless-perf",
        },
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        raw = response.read().decode()
    messages = []
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            event = json.loads(line[5:])
        except ValueError:
            continue
        for row in event.get("result", {}).get("results", []):
            stamp = next((m["value"] for m in row.get("metadata", []) if m.get("key") == "timestamp"), None)
            try:
                message = json.loads(row.get("user_data", "{}")).get("message", "")
                # the timestamp has nanoseconds, and fromisoformat takes at most microseconds
                messages.append((datetime.fromisoformat(stamp[:26]).replace(tzinfo=timezone.utc).timestamp(), message))
            except (ValueError, TypeError):
                continue
    return messages


def _steps(seconds: float, done_at: float, stamps: dict) -> dict:
    """The submit split into COS upload, prepare, create fleet and save, or {} when a line is missing.

    The parts add up to ``seconds``, the time the scheduler logged for the whole submit.
    """
    marks = [done_at - seconds] + [stamps.get(name) for name in ("uploaded", "creating", "created")] + [done_at]
    if None in marks:
        return {}
    # the logged seconds have 2 decimals, so the start can be up to 5 ms off. Clamp it, then check the order
    marks[0] = min(marks[0], marks[1])
    if any(b < a for a, b in zip(marks, marks[1:])):
        return {}
    return {name: round(b - a, 3) for name, a, b in zip(SUBMIT_PARTS, marks, marks[1:])}


# pylint: disable-next=too-many-locals
def submit_times(cloud_logs: CloudLogs, job_ids: list[str], start: float, end: float, log) -> list[dict]:
    """[{"job_id", "seconds", "cos_upload", "prepare", "create_fleet", "save"}] of each job of the run."""
    key = iam.api_key()
    if not key:
        log("no IBM_CLOUD_API_KEY, so no submit times from Cloud Logs")
        return []
    query = (
        "source logs | filter $l.applicationname == 'qiskit-serverless' && $l.subsystemname == 'gateway-scheduler'"
        " | filter $d.message ~ 'Execute job' || $d.message ~ 'COS configured for job_id'"
        " || $d.message ~ 'Submitting job_id' || $d.message ~ 'Submitted job_id' | choose $d.message"
    )
    try:
        messages = _query(cloud_logs, iam.token(key), query, start, end + MARGIN_SECONDS)
    except (OSError, ValueError) as exc:
        log(f"no submit times, Cloud Logs failed: {type(exc).__name__}: {exc}")
        return []
    if len(messages) >= QUERY_LIMIT:
        log(f"Cloud Logs hit the {QUERY_LIMIT} line limit, so some submit times may be missing")
    ours = set(job_ids)
    stamps: dict = {}
    done: dict = {}
    # by time, so a retried submit keeps the stamps of its last attempt
    for at, message in sorted(messages):
        if (match := SUBMIT_LINE.search(message)) and match.group(1) in ours:
            done[match.group(1)] = (float(match.group(2)), at)
            continue
        for name, pattern in STEP_LINES.items():
            if (match := pattern.search(message)) and match.group(1) in ours:
                stamps.setdefault(match.group(1), {})[name] = at
    rows = [
        {"job_id": job_id, "seconds": seconds, **_steps(seconds, at, stamps.get(job_id, {}))}
        for job_id, (seconds, at) in done.items()
    ]
    split = sum(1 for row in rows if has_parts(row))
    log(f"submit times of {len(rows)} of {len(ours)} jobs from Cloud Logs, {split} split into steps")
    return rows
