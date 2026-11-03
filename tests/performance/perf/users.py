"""One simulated user: the tutorial notebook flow, from signing in to getting the result."""

import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from qiskit_serverless import QiskitFunction, ServerlessClient

# the waits of Job.wait_for_final_state(), so a backoff scenario polls like a real SDK user
from qiskit_serverless.core.job import _next_wait, _resets_backoff  # pylint: disable=protected-access
from qiskit_serverless.utils.errors import is_transient_error

from .config import Function
from .rate_limit import RateLimiter
from .tracer import set_context

TERMINAL = {"DONE", "ERROR", "CANCELED"}
# Every simulated user signs in with the same account, so a burst of sign-ins spends one account's IBM Cloud
# rate limit, and some get a 503. Real users each have their own account, so the driver retries a few times.
SIGN_IN_TRIES = 4
SIGN_IN_WAIT_SECONDS = 2.0


def make_client(gateway: str) -> ServerlessClient:
    """A client for the gateway, with the token and instance from the env."""
    kwargs = {"channel": os.environ["GATEWAY_CHANNEL"]} if os.environ.get("GATEWAY_CHANNEL") else {}
    return ServerlessClient(
        host=gateway, token=os.environ["GATEWAY_TOKEN"], instance=os.environ["GATEWAY_INSTANCE"], **kwargs
    )


def sign_in(gateway: str, stop: threading.Event, retries: list) -> ServerlessClient:
    """make_client, tried again on a 429 or 5xx with a random wait, each retry recorded in retries."""
    for attempt in range(1, SIGN_IN_TRIES):
        try:
            return make_client(gateway)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # the client wraps the sign-in error and drops its code, so the code is on the cause
            if not is_transient_error(exc.__cause__) or stop.is_set():
                raise
            retries.append((time.time(), _short(exc)[:200]))
            # random over the whole range, so users who failed together do not retry together
            stop.wait(random.uniform(0, SIGN_IN_WAIT_SECONDS * 2**attempt))
    return make_client(gateway)


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
    sign_in_retries: list = field(default_factory=list)


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
    backoff: bool
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
            client = sign_in(self.gateway, self.stop, result.sign_in_retries)
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
        """Check the status every poll_seconds, or with the SDK backoff. True when the job ended.

        Not wait_for_final_state() itself: it retries a 503 out of sight of the tracer, and ignores the stop event.
        """
        last = None
        step = 0
        deadline = time.time() + self.timeout_seconds
        while not self.stop.is_set() and time.time() < deadline:
            try:
                status = job.status()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                result.poll_errors.append((time.time(), _short(exc)[:200]))
                status = None
            if status is not None and status != last:
                result.statuses.append((time.time(), status))
                if last is not None and _resets_backoff(last, status):
                    step = 0
                last = status
            if status in TERMINAL:
                result.final_status = status
                result.ended_at = time.time()
                return True
            self.stop.wait(_next_wait(step, None) if self.backoff else self.poll_seconds)
            step += 1
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
