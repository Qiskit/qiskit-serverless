"""Builder for the message that mirrors a Functions job to NTC as a workload.

The result is the envelope ``{"function_id", "body"}``: ``function_id`` goes in the URL path and ``body`` is
exactly what NTC receives. It is built from the job's state at the moment the fact became true and can be stored
as-is (for example in ``Outbox.payload``) and sent later by ``core.clients.workload_sender.WorkloadSender``.

NTC replaces the whole row on every call, so ``body`` always carries all ten keys, with ``None`` for the ones the
job has no value for.
"""

from datetime import datetime

from core.models import Job

# Six job states here, five on the NTC side. QUEUED and PENDING both mean "not running yet"; STOPPING is still
# running until it is STOPPED.
_NTC_STATUS = {
    Job.QUEUED: "Queued",
    Job.PENDING: "Queued",
    Job.RUNNING: "Running",
    Job.STOPPING: "Running",
    Job.SUCCEEDED: "Completed",
    Job.FAILED: "Failed",
    Job.STOPPED: "Cancelled",
}


def map_status(job_status: str) -> str:
    """Translate a ``Job`` status into the NTC vocabulary. Raises ValueError for a status it does not know."""
    try:
        return _NTC_STATUS[job_status]
    except KeyError as exc:
        raise ValueError(f"No NTC status for job status {job_status!r}") from exc


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def build_workload_payload(job: Job, status: str, ended_at: datetime | None) -> dict:
    """Build the envelope for ``job``. ``status`` is the internal job status at the time of the fact and
    ``ended_at`` is when the job became terminal (None otherwise); both are arguments, not read from the job,
    because the payload is frozen when the fact happens and not when it is sent."""
    provider = job.program.provider
    return {
        "function_id": str(job.id),
        "body": {
            "name": job.program.title,
            "provider": provider.name if provider else None,
            "crn": job.instance_crn,
            "user_id": job.author.username,
            "status": map_status(status),
            "compute_profile": job.compute_profile_id,
            "size": job.function_size.function_size.upper() if job.function_size else None,
            "created_at": _iso(job.created),
            "running_at": _iso(job.running_started_at),
            "ended_at": _iso(ended_at),
        },
    }
