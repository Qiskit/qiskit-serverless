"""After the run: the status events of each job, and the start time its function printed."""

import re
import time

from .users import make_client

_START = re.compile(r"perf-start (\S+)")


def _last_error(logs: str) -> str | None:
    """The last exception line of a failed job's log, for example "ConnectionError: ..."."""
    errors = [line.strip() for line in logs.splitlines() if re.match(r"^\w+(\.\w+)*(Error|Exception): ", line)]
    return errors[-1][:300] if errors else None


def client_with_retry(gateway: str, log, tries: int = 3):
    """A client. Its sign-in can get a 503 from the gateway, so try a few times."""
    for attempt in range(1, tries + 1):
        try:
            return make_client(gateway)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            if attempt == tries:
                raise
            log(f"sign-in failed, trying again: {type(exc).__name__}")
            time.sleep(10 * attempt)
    raise RuntimeError("unreachable")


def _event_error(events) -> str | None:
    """The last ERROR event, for example "FLEET_SUBMIT_FAILED: ApiException ...". A job that never ran has no log."""
    errors = [event.data or {} for event in events if event.event_type == "ERROR"]
    if not errors:
        return None
    data = errors[-1]
    return f"{data.get('code')}: {data.get('exception')} {data.get('args')}"[:300]


def collect_jobs(gateway: str, rows: list[dict], log) -> list[dict]:
    """One row per job: its STATUS_CHANGE events, the perf-start time from its log, and the error of a failed job."""
    client = client_with_retry(gateway, log)
    jobs = []
    for row in rows:
        if not row.get("job_id"):
            continue
        job = {"job_id": row["job_id"], "user": row["user"], "events": [], "started_at": None}
        event_error = None
        try:
            events = client.events(row["job_id"])
            job["events"] = [
                {"created": event.created, "status": (event.data or {}).get("status")}
                for event in events
                if event.event_type == "STATUS_CHANGE"
            ]
            event_error = _event_error(events)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            log(f"events of job {row['job_id']} failed: {type(exc).__name__}")
        try:
            logs = client.logs(row["job_id"]) or ""
            match = _START.search(logs)
            job["started_at"] = match.group(1) if match else None
            if row.get("final_status") == "ERROR":
                job["error"] = _last_error(logs)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            log(f"logs of job {row['job_id']} failed: {type(exc).__name__}")
        if row.get("final_status") == "ERROR" and not job.get("error"):
            job["error"] = event_error
        jobs.append(job)
    return jobs
