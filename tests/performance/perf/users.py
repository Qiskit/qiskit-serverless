"""One simulated user: the tutorial notebook flow, from signing in to getting the result."""

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from qiskit_serverless import QiskitFunction, ServerlessClient

from .config import Function
from .rate_limit import RateLimiter
from .tracer import set_context

TERMINAL = {"DONE", "ERROR", "CANCELED"}


def make_client(gateway: str) -> ServerlessClient:
    """A client for the gateway, with the token and instance from the env."""
    kwargs = {"channel": os.environ["GATEWAY_CHANNEL"]} if os.environ.get("GATEWAY_CHANNEL") else {}
    return ServerlessClient(
        host=gateway, token=os.environ["GATEWAY_TOKEN"], instance=os.environ["GATEWAY_INSTANCE"], **kwargs
    )


def function_for_upload(function: Function, working_dir: str, title: str) -> QiskitFunction:
    """The function folder as a Fleets custom function, with its sizes."""
    return QiskitFunction(
        title=title,
        entrypoint=function.entrypoint,
        working_dir=working_dir,
        runner="fleets",
        sizes_map=function.sizes,
        default_size=function.default_size,
    )


@dataclass
class UserResult:  # pylint: disable=too-many-instance-attributes
    """What one user saw."""

    user: int
    job_id: str | None = None
    submitted_at: float | None = None
    final_status: str | None = None
    ended_at: float | None = None
    result_ok: bool | None = None
    fleet_id: str | None = None
    fleet_deleted: bool = False
    error: str | None = None
    statuses: list = field(default_factory=list)
    poll_errors: list = field(default_factory=list)


def _short(exc: Exception) -> str:
    return f"{type(exc).__name__}: {' '.join(str(exc).split())[:300]}"


@dataclass
class User:  # pylint: disable=too-many-instance-attributes
    """The settings one user needs. Its run() follows the tutorial notebook."""

    gateway: str
    user: int
    upload: QiskitFunction
    arguments: dict
    poll_seconds: float
    timeout_seconds: float
    ready: threading.Barrier
    limiter: RateLimiter
    stop: threading.Event
    on_job: Callable[[int, str], None]
    delete_fleet: Callable[[str], bool] | None = None

    def run(self, result: UserResult) -> None:
        """Sign in, upload its own copy, wait until every user has, take a token, run, poll, then get the result."""
        set_context(user=self.user)
        try:
            client = make_client(self.gateway)
            function = client.upload(self.upload)
            if function is None:
                raise RuntimeError(f"upload of {self.upload.title} returned nothing")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # a failed user still arrives at the barrier, so the others run without it
            result.error = f"before run: {_short(exc)}"
            function = None
        try:
            self.ready.wait()
        except threading.BrokenBarrierError:
            return
        if function is None or not self.limiter.wait(self.stop):
            return
        try:
            result.submitted_at = time.time()
            job = function.run(**self.arguments)
            result.job_id = job.job_id
            self.on_job(self.user, job.job_id)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            result.error = f"run: {_short(exc)}"
            return
        if self._poll(job, result) and result.final_status != "CANCELED":
            self._get_result(job, result)
        # the last poll filled raw_data, so the fleet id needs no extra request
        result.fleet_id = job.raw_data.get("fleet_id")
        if result.final_status and result.fleet_id and self.delete_fleet:
            result.fleet_deleted = self.delete_fleet(result.fleet_id)

    def _poll(self, job, result: UserResult) -> bool:
        """Check the status every poll_seconds. True when the job ended."""
        last = None
        deadline = time.time() + self.timeout_seconds
        while not self.stop.is_set() and time.time() < deadline:
            try:
                status = job.status()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                result.poll_errors.append((time.time(), _short(exc)[:200]))
                self.stop.wait(self.poll_seconds)
                continue
            if status != last:
                result.statuses.append((time.time(), status))
                last = status
            if status in TERMINAL:
                result.final_status = status
                result.ended_at = time.time()
                return True
            self.stop.wait(self.poll_seconds)
        return False

    def _get_result(self, job, result: UserResult) -> None:
        """job.result() with no wait, because the job already ended. A failed job raises its error."""
        try:
            job.result(wait=False)
            result.result_ok = True
        except Exception as exc:  # pylint: disable=broad-exception-caught
            result.result_ok = False
            if result.final_status == "DONE":
                result.error = f"result: {_short(exc)}"
