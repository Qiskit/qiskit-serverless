"""Cleanup resources command."""

import logging

from concurrency.exceptions import RecordModifiedError
from django.conf import settings
from django.core.management.base import BaseCommand
from ray.dashboard.modules.job.common import JobStatus

from api.domain.function import check_logs
from api.models import Job
from api.ray import get_job_handler
from api.schedule import (
    check_job_timeout,
    handle_job_status_not_available,
    fail_job_insufficient_resources,
)
from api.utils import ray_job_status_to_model_job_status

logger = logging.getLogger("commands")


def update_job_status(job: Job):

    if job.status != JobStatus.RUNNING and job.status != JobStatus.PENDING:
        # this is an obvious validation to remind us the only possible states for the job
        return False

    """Update status of one job."""
    if not job.compute_resource:
        logger.warning(
            "Job [%s] does not have compute resource associated with it. Skipping.",
            job.id,
        )
        return False

    # save the original status to check if it changes during the update
    job_original_status = job.status

    # the job_job_handler uses retry, but if it fails, returns None
    job_handler = get_job_handler(job.compute_resource.host)
    if job_handler:
        try:
            ray_job_status = job_handler.status(job.ray_job_id)
            job.status = ray_job_status_to_model_job_status(ray_job_status)
        except Exception as e:
            logger.warning(
                "Failed to get job status for job [%s]: %s",
                job.id,
                str(e),
            )
            job.status = Job.FAILED
    else:
        logger.warning(
            "Failed to connect to ray cluster for job [%s]: %s",
            job.id,
            job.compute_resource.host,
        )
        job.status = Job.FAILED

    # Check for timeout (only if not failed)
    if job.status != Job.FAILED and check_job_timeout(job):
        job.status = Job.STOPPED

    # Update job status if changed
    if job.status != job_original_status:
        # if the original state is Running/Pending, then the status now is Failed/Stopped/Succeeded
        logger.info(
            "Job [%s] of [%s] changed from [%s] to [%s]",
            job.id,
            job.author,
            job_original_status,
            job.status,
        )
        job.sub_status = None
        job.env_vars = "{}"
        handle_job_status_not_available(job)

    # Try to get and update logs
    if job_handler:
        try:
            logs = job_handler.logs(job.ray_job_id)
            job.logs = check_logs(logs, job)
            # check if job is resource constrained
            no_resources_log = "No available node types can fulfill resource request"
            if no_resources_log in job.logs:
                job_new_status = fail_job_insufficient_resources(job)
                job.status = job_new_status
                # cleanup env vars
                job.env_vars = "{}"
        except Exception as e:
            logger.warning(
                "Failed to get logs for job [%s]: %s",
                job.id,
                str(e),
            )

    try:
        job.save()
        return True
    except RecordModifiedError:
        logger.warning("Job [%s] record has not been updated due to lock.", job.id)
        return False


class Command(BaseCommand):
    """Update status of jobs."""

    help = "Update running job statuses and logs."

    def handle(self, *args, **options):
        # update job statuses
        # pylint: disable=too-many-branches
        max_ray_clusters_possible = settings.LIMITS_MAX_CLUSTERS
        max_gpu_clusters_possible = settings.LIMITS_GPU_CLUSTERS
        update_classical_jobs = max_ray_clusters_possible > 0
        update_gpu_jobs = max_gpu_clusters_possible > 0

        if update_classical_jobs:
            updated_jobs_counter = 0
            jobs = Job.objects.filter(status__in=Job.RUNNING_STATUSES, gpu=False)
            for job in jobs:
                if update_job_status(job):
                    updated_jobs_counter += 1

            logger.info("Updated %s classical jobs.", updated_jobs_counter)

        if update_gpu_jobs:
            updated_jobs_counter = 0
            jobs = Job.objects.filter(status__in=Job.RUNNING_STATUSES, gpu=True)
            for job in jobs:
                if update_job_status(job):
                    updated_jobs_counter += 1

            logger.info("Updated %s GPU jobs.", updated_jobs_counter)
