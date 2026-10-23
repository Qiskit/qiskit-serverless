"""After a run: cancel its jobs that are still active, wait for them to end, then delete their fleets."""

import http.client
import json
import threading
import time
import urllib.error
import urllib.request

from qiskit_serverless.exception import QiskitServerlessException

from . import iam
from .config import CodeEngine
from .run_dir import RunDir
from .jobs import client_with_retry

# how long to wait for the canceled jobs to end before deleting their fleets
CANCEL_WAIT_SECONDS = 300
CANCEL_POLL_SECONDS = 10
# the gateway's own status names, as client.job() returns them in raw_data
ENDED = {"SUCCEEDED", "FAILED", "STOPPED"}


def cancel_jobs(gateway: str, job_ids: list[str], log) -> dict[str, str | None]:
    """Cancel the active jobs, wait until every job ends, and return {job id: fleet id}."""
    client = client_with_retry(gateway, log)
    fleets: dict[str, str | None] = {}
    canceled: set[str] = set()
    deadline = time.time() + CANCEL_WAIT_SECONDS
    pending = list(job_ids)
    while pending:
        for job_id in list(pending):
            try:
                # one GET: client.job() reads the status and the fleet id together
                job = client.job(job_id)
            except QiskitServerlessException as exc:
                log(f"{job_id}: {' '.join(str(exc).split())[:120]}")
                # only a 404 means the job is gone. A 503 or a dropped connection is tried again on the next loop
                if "Code: 404" in str(exc):
                    pending.remove(job_id)
                continue
            try:
                if job is None or job.raw_data.get("status") in ENDED:
                    fleets[job_id] = job.fleet_id if job is not None else None
                    pending.remove(job_id)
                elif job_id not in canceled:
                    canceled.add(job_id)
                    log(f"cancel {job_id}: {job.cancel()}")
            except Exception as exc:  # pylint: disable=broad-exception-caught
                log(f"{job_id} failed: {type(exc).__name__}: {exc}")
        if not pending or time.time() > deadline:
            break
        time.sleep(CANCEL_POLL_SECONDS)
    for job_id in pending:
        log(f"job {job_id} did not end in {CANCEL_WAIT_SECONDS} s, so its fleet is kept")
    return fleets


class FleetDeleter:
    """Deletes and counts fleets with the Code Engine REST API. One IAM token for every call, shared by the users."""

    # an IAM token lasts an hour, so refresh it well before
    TOKEN_SECONDS = 1800

    def __init__(self, code_engine: CodeEngine | None, log):
        self._code_engine = code_engine
        self._log = log
        self._lock = threading.Lock()
        self._bearer: str | None = None
        self._since = 0.0

    def _token(self) -> str | None:
        with self._lock:
            if self._bearer is None or time.time() - self._since > self.TOKEN_SECONDS:
                key = iam.api_key()
                if not key:
                    return None
                self._bearer, self._since = iam.token(key), time.time()
            return self._bearer

    def delete(self, fleet_id: str) -> bool:
        """Delete one fleet. True when it is gone, including when it was gone already."""
        if self._code_engine is None:
            return False
        try:
            bearer = self._token()
        except (OSError, ValueError, KeyError) as exc:
            self._log(f"delete fleet {fleet_id}: the IAM token failed: {type(exc).__name__}")
            return False
        if bearer is None:
            return False
        ce = self._code_engine
        url = f"https://api.{ce.region}.codeengine.cloud.ibm.com/v2/projects/{ce.project_id}/fleets/{fleet_id}"
        request = urllib.request.Request(url, method="DELETE", headers={"Authorization": f"Bearer {bearer}"})
        try:
            with urllib.request.urlopen(request, timeout=60):
                return True
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return True
            self._log(f"delete fleet {fleet_id} failed: HTTP {exc.code} {exc.read()[:200].decode(errors='replace')}")
        except (OSError, http.client.HTTPException) as exc:
            self._log(f"delete fleet {fleet_id} failed: {type(exc).__name__}: {exc}")
        return False

    def count(self) -> int | None:
        """How many fleets the project holds, deleting ones included, since Code Engine counts them in its 1000 cap."""
        if self._code_engine is None:
            return None
        ce = self._code_engine
        url = f"https://api.{ce.region}.codeengine.cloud.ibm.com/v2/projects/{ce.project_id}/fleets?limit=100"
        total = 0
        try:
            bearer = self._token()
            if bearer is None:
                return None
            while url:
                request = urllib.request.Request(url, headers={"Authorization": f"Bearer {bearer}"})
                with urllib.request.urlopen(request, timeout=60) as response:
                    page = json.load(response)
                total += len(page.get("fleets", []))
                url = (page.get("next") or {}).get("href")
        except (OSError, ValueError, KeyError, http.client.HTTPException) as exc:
            self._log(f"could not count the fleets: {type(exc).__name__}: {exc}")
            return None
        return total


def cleanup(gateway: str, code_engine: CodeEngine | None, run_dir: RunDir, log) -> None:
    """Cancel the run's jobs, then delete the fleets that are left."""
    fleets = cancel_jobs(gateway, run_dir.job_ids(), log)
    deleted = {row["fleet_id"] for row in run_dir.read("users.jsonl") if row.get("fleet_deleted")}
    fleet_ids = sorted({f for f in fleets.values() if f} - deleted)
    if code_engine is None:
        log(f"no code_engine in scenarios.yaml, so the {len(fleet_ids)} fleets are kept")
        return
    if not iam.api_key():
        log(f"no IBM_CLOUD_API_KEY, so the {len(fleet_ids)} fleets are kept")
        return
    deleter = FleetDeleter(code_engine, log)
    gone = sum(deleter.delete(fleet_id) for fleet_id in fleet_ids)
    log(f"deleted {gone} of {len(fleet_ids)} fleets left after the run, {len(deleted)} were deleted by their users")
