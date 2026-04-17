"""Job status update service."""

import logging

from concurrency.exceptions import RecordModifiedError
from core.models import JobEvent

from core.services.runners import get_runner, RunnerError
from core.model_managers.job_events import JobEventContext, JobEventOrigin

logger = logging.getLogger("core.services.job_status")


def update_job_status(job):
    """
    Update status of one job (simplified version for api use).

    This is a simplified version that updates job status from Ray
    without scheduler-specific logic like timeout checks.

    Args:
        job: Job model instance

    Returns:
        bool: True if status changed, False otherwise
    """

    if not job.compute_resource:
        logger.warning(
            "Job [%s] does not have compute resource associated with it. Skipping.",
            job.id,
        )
        return False

    status_has_changed = False
    runner = get_runner(job)

    try:
        job_new_status = runner.status()
    except RunnerError as ex:
        logger.warning("Job [%s] status update failed: %s", job.id, ex)
        return False

    if job_new_status != job.status:
        logger.info(
            "Job [%s] of [%s] changed from [%s] to [%s]",
            job.id,
            job.author,
            job.status,
            job_new_status,
        )
        status_has_changed = True
        job.status = job_new_status
        # cleanup env vars
        if job.in_terminal_state():
            job.sub_status = None
            job.env_vars = "{}"

    try:
        job.save()
        if status_has_changed:
            JobEvent.objects.add_status_event(
                job_id=job.id,
                origin=JobEventOrigin.API,
                context=JobEventContext.UPDATE_JOB_STATUS,
                status=job.status,
            )
    except RecordModifiedError:
        logger.warning("Job [%s] record has not been updated due to lock.", job.id)

    return status_has_changed
