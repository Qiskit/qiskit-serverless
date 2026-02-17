"""Job status update service."""

import logging

from concurrency.exceptions import RecordModifiedError
from core.models import Job, JobEvent

from core.services.ray import get_job_handler
from core.utils import check_logs, ray_job_status_to_model_job_status
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
    job_new_status = Job.PENDING
    job_handler = get_job_handler(job.compute_resource.host)
    ray_job_status = job_handler.status(job.ray_job_id) if job_handler else None

    if ray_job_status:
        job_new_status = ray_job_status_to_model_job_status(ray_job_status)

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

    if job_handler:
        logs = job_handler.logs(job.ray_job_id)
        job.logs = check_logs(logs, job)

    try:
        job.save()
    except RecordModifiedError:
        logger.warning("Job [%s] record has not been updated due to lock.", job.id)

    if status_has_changed:
        JobEvent.objects.add_status_event(
            job_id=job.id,
            origin=JobEventOrigin.API,
            context=JobEventContext.UPDATE_JOB_STATUS,
            status=job.status,
            sub_status=job.sub_status,
        )

    return status_has_changed
