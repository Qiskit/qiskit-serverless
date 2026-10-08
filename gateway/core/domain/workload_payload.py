"""Builder for the message that mirrors a Functions job to the Runtime API as a workload.

The result is the envelope ``{"function_id", "body"}``: ``function_id`` goes in the URL path and ``body`` is
exactly what the Runtime API receives. The builder reads the job's events (``running_at`` and ``ended_at`` come from
them), so it needs the database. Build it right after the status change, inside the same transaction:
``JobTransitionService._change_status`` (``core/services/job_transitions.py``) adds the status event before it
updates the job row, both in one transaction, so both are visible there. The result can then be stored as-is (for
example in ``Outbox.payload``) and sent later by ``core.clients.workload_sender.WorkloadSender``. A terminal job with
no terminal event gets ``ended_at=None``.

The Runtime API replaces the whole row on every call, so ``body`` always carries all ten keys, with ``None`` for the
ones the job has no value for.
"""

from datetime import datetime

from django.utils.timezone import is_naive

from core.models import Job, JobEvent

# Six job states here, five on the Runtime API side. QUEUED and PENDING both mean "not running yet"; STOPPING is still
# running until it is STOPPED.
_RUNTIME_API_STATUS = {
    Job.QUEUED: "Queued",
    Job.PENDING: "Queued",
    Job.RUNNING: "Running",
    Job.STOPPING: "Running",
    Job.SUCCEEDED: "Completed",
    Job.FAILED: "Failed",
    Job.STOPPED: "Cancelled",
}


def map_status(job_status: str) -> str:
    """Translate a ``Job`` status into the Runtime API vocabulary. Raises ValueError for a status it does not know."""
    try:
        return _RUNTIME_API_STATUS[job_status]
    except KeyError as exc:
        raise ValueError(f"No Runtime API status for job status {job_status!r}") from exc


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if is_naive(value):
        raise ValueError(
            f"Datetime {value.isoformat()} has no timezone, the Runtime API requires RFC 3339 with an offset"
        )
    return value.isoformat()


def build_workload_payload(job: Job) -> dict:
    """Build the envelope for ``job`` from its current state and its event history. ``running_at`` and ``ended_at``
    are the times of the first RUNNING and the first terminal status events; ``ended_at`` is only looked up while the
    job is terminal, and stays None if a terminal job has no terminal event."""
    provider = job.program.provider
    ended_at = JobEvent.objects.first_terminal_at(job.id) if job.in_terminal_state() else None
    return {
        "function_id": str(job.id),
        "body": {
            "name": job.program.title,
            "provider": provider.name if provider else None,
            "crn": job.instance_crn,
            "user_id": job.author.username,
            "status": map_status(job.status),
            "compute_profile": job.compute_profile_id,
            "size": job.function_size.function_size.upper() if job.function_size else None,
            "created_at": _iso(job.created),
            "running_at": _iso(JobEvent.objects.first_running_at(job.id)),
            "ended_at": _iso(ended_at),
        },
    }
