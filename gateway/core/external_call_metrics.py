"""Duration of the operations the scheduler makes against other services, one sample per operation.

Marcelo's hook in ``core/ibm_cloud/call_metrics.py`` times each single Code Engine and COS request. This module times
what the scheduler does with them (reading the status of a job, uploading a job) plus the IAM and Runtime API calls
that hook does not see.

Only the scheduler records. The gateway runs several gunicorn workers without Prometheus multiprocess mode, so each
scrape would read one random worker and the numbers would be wrong. ``core`` cannot import ``scheduler`` either, so
the histogram is created by ``enable()``, which only ``run_scheduler`` calls. In the gateway nothing is recorded.
"""

import functools
import socket
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from prometheus_client import REGISTRY, CollectorRegistry, Histogram

from core.domain.exceptions.invalid_job_transition_exception import InvalidJobTransitionException

# The values of the ``operation`` label, a closed list so the cardinality stays fixed.
FLEET_STATUS_READ = "fleet_status_read"
FLEET_SUBMIT_UPLOAD = "fleet_submit_upload"
RUNTIME_API_PUT = "runtime_api_put"
IAM_TOKEN = "iam_token"
JOB_TRANSITION_QUEUED_TO_PENDING = "job_transition_queued_to_pending"
JOB_TRANSITION_PENDING_TO_RUNNING = "job_transition_pending_to_running"
JOB_IN_PROGRESS_EVENT = "job_in_progress_event"
JOB_TRANSITION_TO_TERMINAL = "job_transition_to_terminal"
JOB_LAST_EVENT_QUERY = "job_last_event_query"

STATUS_OK = "ok"
STATUS_TIMEOUT = "timeout"
STATUS_ERROR = "error"
STATUS_REJECTED = "rejected"

_DURATION: Histogram | None = None


@dataclass
class Observation:
    """What the ``with`` block of ``observe_operation`` hands to its caller. The status is ``ok``, ``timeout`` or
    ``error`` by how the block ended, unless the caller sets it: an HTTP call answers with a code and does not raise
    on a 4xx or a 5xx, so it sets the code, as the request metrics of Code Engine and COS do."""

    status: str | None = None


def enable(registry: CollectorRegistry = REGISTRY) -> None:
    """Start recording, in ``registry``. Called once at scheduler startup, never in the gateway."""
    global _DURATION  # pylint: disable=global-statement
    _DURATION = Histogram(
        "scheduler_operation_duration_seconds",
        "Duration of one operation of the scheduler against another service. status is ok, timeout or error, "
        "or the HTTP code when the operation is an HTTP call that answers with one.",
        labelnames=("operation", "status"),
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 40, 60, 120, 300, float("inf")),
        registry=registry,
    )


def disable() -> None:
    """Stop recording. For tests."""
    global _DURATION  # pylint: disable=global-statement
    _DURATION = None


def _is_timeout(exc: BaseException) -> bool:
    """Whether the exception, or anything it was raised from, is a timeout. The libraries involved (requests, urllib3,
    botocore, the IAM SDK) each have their own timeout classes, and wrap each other, so the name is what they share."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (TimeoutError, socket.timeout)) or "Timeout" in type(current).__name__:
            return True
        current = current.__cause__ or current.__context__
    return False


@contextmanager
def observe_operation(operation: str) -> Iterator[Observation]:
    """Time the block and record it under ``operation``, if recording is enabled. The exception, if any, is raised
    again untouched."""
    observation = Observation()
    started = time.perf_counter()
    status = STATUS_OK
    try:
        yield observation
    except BaseException as exc:
        status = STATUS_TIMEOUT if _is_timeout(exc) else STATUS_ERROR
        raise
    finally:
        if _DURATION is not None:
            _DURATION.labels(operation=operation, status=observation.status or status).observe(
                time.perf_counter() - started
            )


def observer_method(operation: str):
    """Record how long the whole method took (its transaction and the sends after it) under ``operation``, in the
    scheduler. In the gateway recording is off and this does nothing. Put it on the method that does the work, never
    on one that only delegates to another observed method, or the operation would be counted twice."""

    def decorator(method):
        @functools.wraps(method)
        def wrapper(*args, **kwargs):
            with observe_operation(operation) as observation:
                try:
                    return method(*args, **kwargs)
                except InvalidJobTransitionException:
                    # The job was already moved by someone else (a user stopped it): an expected race, not a failure.
                    observation.status = STATUS_REJECTED
                    raise

        return wrapper

    return decorator
