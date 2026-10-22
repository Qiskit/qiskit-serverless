"""Best effort mirror of the intermediate statuses of a Functions job (Pending, Running, Stopping) to the Runtime API.

The terminal status does not go through here: it goes through the WORKLOAD outbox channel, which guarantees delivery
and repairs any intermediate status lost here. ``send`` runs on the scheduler thread, and only the network call runs on
the ``BackgroundPool.RUNTIME_API`` pool, so the scheduler loop never waits for the Runtime API.
"""

import logging

from django.db.utils import InterfaceError, OperationalError
from prometheus_client import Counter

from core.clients.functions_operator_client import get_functions_operator_client
from core.config_key import ConfigKey
from core.domain.workload_payload import _STATUS, build_workload_payload, is_mirrored, should_be_mirrored
from core.models import Config, Job
from core.services.background_executor import (
    BackgroundExecutorNotInitializedError,
    BackgroundPool,
    get_background_executor,
)

logger = logging.getLogger("core.WorkloadBestEffortMirror")

_PUT_TIMEOUT = 3  # seconds
_STATUSES = ("Pending", "Running", "Stopping")
_OUTCOMES = ("sent", "failed", "dropped")
# The same two classes as DB_EXCEPTIONS in scheduler/health.py, which core may not import. They are re-raised so the
# scheduler still counts a database outage.
_DB_OUTAGE = (OperationalError, InterfaceError)

_MIRROR = Counter(
    "workload_best_effort_mirror_total",
    "Intermediate workload statuses by status and outcome. sent also counts a PUT that the Runtime API accepted and "
    "ignored (202, for example a workload that is already terminal).",
    labelnames=("status", "outcome"),
)
for _status in _STATUSES:
    for _outcome in _OUTCOMES:
        _MIRROR.labels(_status, _outcome)


def _count(status: str | None, outcome: str) -> None:
    if status in _STATUSES:
        _MIRROR.labels(status, outcome).inc()


def _put(function_id: str, body: dict, status: str) -> None:
    """The task of the pool: network only, never the ORM, and it never raises."""
    try:
        get_functions_operator_client().put_function(function_id, body, timeout=_PUT_TIMEOUT)
    except Exception as ex:  # pylint: disable=broad-exception-caught
        logger.warning("job_id=%s status=%s workload status not sent: %s", function_id, status, type(ex).__name__)
        _count(status, "failed")
        return
    _count(status, "sent")


class WorkloadBestEffortMirror:
    """Sends the current status of a mirrored job. Building it does no work."""

    def send(self, job: Job) -> None:
        """Send the status of ``job``, which the caller has already committed. It never raises, except for a database
        outage, which must reach the scheduler. The checks go from the cheapest to the dearest: the job itself (no
        query), the Config switch (cached), the mirror row (one query), the pool, and last the payload."""
        if not should_be_mirrored(job):
            return
        try:
            if not Config.get_bool(ConfigKey.WORKLOADS_STATUS_UPDATES_ENABLED):
                return
        except _DB_OUTAGE:
            raise
        except Exception as ex:  # pylint: disable=broad-exception-caught
            logger.warning("job_id=%s workload status switch unreadable, treated as off: %s", job.id, type(ex).__name__)
            return

        status = _STATUS.get(job.status)
        try:
            if not is_mirrored(job):
                return
            replace_key = f"job:{job.id}"
            executor = get_background_executor()
            if not executor.would_accept(BackgroundPool.RUNTIME_API, replace_key):
                _count(status, "dropped")
                return
            envelope = build_workload_payload(job)
            future = executor.submit(
                BackgroundPool.RUNTIME_API,
                _put,
                envelope["function_id"],
                envelope["body"],
                status,
                replace_key=replace_key,
            )
            if future is None:
                _count(status, "dropped")
        except _DB_OUTAGE:
            raise
        except BackgroundExecutorNotInitializedError:
            logger.error("job_id=%s workload status not sent: the background executor is not initialized", job.id)
            _count(status, "failed")
        except Exception as ex:  # pylint: disable=broad-exception-caught
            logger.warning("job_id=%s workload status not sent: %s", job.id, type(ex).__name__)
            _count(status, "failed")
