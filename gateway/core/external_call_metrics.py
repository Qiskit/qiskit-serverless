"""Duration of the operations the scheduler makes against other services, one sample per operation.

Marcelo's hook in ``core/ibm_cloud/call_metrics.py`` times each single Code Engine and COS request. This module times
what the scheduler does with them (reading the status of a job, uploading a job) plus the IAM and Runtime API calls
that hook does not see.

Only the scheduler records. The gateway runs several gunicorn workers without Prometheus multiprocess mode, so each
scrape would read one random worker and the numbers would be wrong. ``core`` cannot import ``scheduler`` either, so
the histogram is created by ``enable()``, which only ``run_scheduler`` calls. In the gateway nothing is recorded.
"""

import socket
import time
from contextlib import contextmanager
from typing import Iterator

from prometheus_client import REGISTRY, CollectorRegistry, Histogram

# The values of the ``operation`` label, a closed list so the cardinality stays fixed.
FLEET_STATUS_READ = "fleet_status_read"
FLEET_SUBMIT_UPLOAD = "fleet_submit_upload"
RUNTIME_API_PUT = "runtime_api_put"
IAM_TOKEN = "iam_token"

OUTCOME_OK = "ok"
OUTCOME_TIMEOUT = "timeout"
OUTCOME_ERROR = "error"

_DURATION: Histogram | None = None


def enable(registry: CollectorRegistry = REGISTRY) -> None:
    """Start recording, in ``registry``. Called once at scheduler startup, never in the gateway."""
    global _DURATION  # pylint: disable=global-statement
    _DURATION = Histogram(
        "scheduler_operation_duration_seconds",
        "Duration of one operation of the scheduler against another service, by operation and outcome "
        "(ok, timeout or error).",
        labelnames=("operation", "outcome"),
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
def observe_operation(operation: str) -> Iterator[None]:
    """Time the block and record it under ``operation``, if recording is enabled. The exception, if any, is raised
    again untouched."""
    started = time.perf_counter()
    outcome = OUTCOME_OK
    try:
        yield
    except BaseException as exc:
        outcome = OUTCOME_TIMEOUT if _is_timeout(exc) else OUTCOME_ERROR
        raise
    finally:
        if _DURATION is not None:
            _DURATION.labels(operation=operation, outcome=outcome).observe(time.perf_counter() - started)
