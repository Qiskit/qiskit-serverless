"""Best effort mirror of the intermediate statuses of a Functions job (Pending, Running, Stopping) to the Runtime API.

The terminal status does not go through here: it goes through the WORKLOAD outbox channel, which guarantees delivery
and repairs any intermediate status lost here. ``send`` runs on the scheduler thread, and only the network call runs on
the ``BackgroundPool.RUNTIME_API`` pool, so the scheduler loop never waits for the Runtime API.
"""

import logging
from abc import ABC, abstractmethod

from django.db.utils import InterfaceError, OperationalError
from prometheus_client import Counter

from core.clients.functions_operator_client import get_functions_operator_client
from core.domain.workload_payload import (
    WORKLOAD_STATUS_MAPPING,
    build_workload_payload,
    is_mirrored,
    should_be_mirrored,
)
from core.models import Job
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
# scheduler still counts a database outage. An executor that was never initialized is a programming error and is
# re-raised too.
_DB_OUTAGE = (OperationalError, InterfaceError)

_MIRROR = Counter(
    "workload_best_effort_mirror_total",
    "Intermediate workload statuses by status and outcome. sent also counts a PUT that the Runtime API accepted and "
    "ignored (202, for example a workload that is already terminal). A status replaced in the queue by a newer one of "
    "the same job is not counted here (the executor counts it as replaced), so the sum can be below the transitions.",
    labelnames=("status", "outcome"),
)
for _status in _STATUSES:
    for _outcome in _OUTCOMES:
        _MIRROR.labels(_status, _outcome)


def _count(status: str | None, outcome: str) -> None:
    if status in _STATUSES:
        _MIRROR.labels(status, outcome).inc()


def _put_background_task(function_id: str, body: dict, status: str) -> None:
    """The task of the pool: network only, never the ORM, and it never raises."""
    try:
        get_functions_operator_client().put_function(function_id, body, timeout=_PUT_TIMEOUT)
    except Exception as ex:  # pylint: disable=broad-exception-caught
        logger.warning("job_id=%s status=%s workload status not sent: %s", function_id, status, type(ex).__name__)
        _count(status, "failed")
        return
    _count(status, "sent")


class WorkloadMirrorSender(ABC):
    """Sends the current status of a job to the Runtime API, once the caller has committed it."""

    @abstractmethod
    def send(self, job: Job) -> None:
        """Send the status of ``job``. It never raises, except for a database outage and for a background executor that
        was never initialized (a programming error)."""


class NoOpWorkloadMirror(WorkloadMirrorSender):
    """Sends nothing. It is the default of JobTransitionService, so the gateway, which has no background executor,
    mirrors no status."""

    def send(self, job: Job) -> None:
        """Does nothing: no Config, no database and no executor."""


class WorkloadBestEffortMirror(WorkloadMirrorSender):
    """Sends the current status of a mirrored job. Building it does no work."""

    def send(self, job: Job) -> None:
        """Send the status of ``job``, which the caller has already committed. It never raises, except for a database
        outage, which must reach the scheduler, and for a background executor that was never initialized, which is a
        programming error (the scheduler initializes it at boot). The checks go from the cheapest to the dearest: the
        job itself (no query), the mirror row (one query), the pool, and last the payload.

        Raises:
            OperationalError, InterfaceError: the database is down.
            BackgroundExecutorNotInitializedError: nobody called ``init()`` on the background executor.
        """
        if not should_be_mirrored(job):
            return

        status = WORKLOAD_STATUS_MAPPING.get(job.status)
        try:
            if not is_mirrored(job):
                return
            replace_key = f"job:{job.id}"
            executor = get_background_executor()
            if not executor.would_accept(BackgroundPool.RUNTIME_API, replace_key):
                # We did what we could, but it couldn't be sent... message is lost,
                # that's what best effort is all about...
                _count(status, "dropped")
                return
            envelope = build_workload_payload(job)
            future = executor.submit(
                BackgroundPool.RUNTIME_API,
                _put_background_task,
                envelope["function_id"],
                envelope["body"],
                status,
                replace_key=replace_key,
            )
            if future is None:
                _count(status, "dropped")
        except (*_DB_OUTAGE, BackgroundExecutorNotInitializedError):
            raise
        except Exception as ex:  # pylint: disable=broad-exception-caught
            logger.warning("job_id=%s workload status not sent: %s", job.id, type(ex).__name__)
            _count(status, "failed")
