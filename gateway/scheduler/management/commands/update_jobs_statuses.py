"""Cleanup resources command."""

import logging

from concurrency.exceptions import RecordModifiedError
from django.conf import settings
from django.core.management.base import BaseCommand

from api.domain.function import check_logs
from api.models import Job
from core.services.ray import get_job_handler
from scheduler.schedule import (
    check_job_timeout,
    handle_job_status_not_available,
    fail_job_insufficient_resources,
)
from api.utils import ray_job_status_to_model_job_status

logger = logging.getLogger("commands")


def update_job_status(job: Job):
    """Update status of one job."""
    if not job.compute_resource:
        logger.warning(
            "Job [%s] does not have compute resource associated with it. Skipping.",
            job.id,
        )
        return False

    status_has_changed = False
    job_new_status = Job.PENDING
    success = False
    job_handler = get_job_handler(job.compute_resource.host)

    try:
        ray_job_status = job_handler.status(job.ray_job_id) if job_handler else None
    except RuntimeError as ex:
        logger.warning(
            "Job [%s] marked as FAILED because Ray get_job_status: %s", job.id, str(ex)
        )
        job.status = Job.FAILED
        job.sub_status = None
        job.env_vars = "{}"
        try:
            job.save()
        except RecordModifiedError:
            logger.warning("Job [%s] record has not been updated due to lock.", job.id)
        return True

    if ray_job_status:
        job_new_status = ray_job_status_to_model_job_status(ray_job_status)
        success = True

    if check_job_timeout(job):
        job_new_status = Job.STOPPED

    if not success:
        job_new_status = handle_job_status_not_available(job, job_new_status)

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
        # check if job is resource constrained
        no_resources_log = "No available node types can fulfill resource request"
        if no_resources_log in job.logs:
            job_new_status = fail_job_insufficient_resources(job)
            job.status = job_new_status
            # cleanup env vars
            job.env_vars = "{}"

    try:
        job.save()
    except RecordModifiedError:
        logger.warning("Job [%s] record has not been updated due to lock.", job.id)

    return status_has_changed


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

            if len(jobs) > 0:
                if updated_jobs_counter != len(jobs):
                    logger.info(
                        "Updated %s of %s classical jobs. Pending: ",
                        updated_jobs_counter,
                        len(jobs),
                        len(jobs) - updated_jobs_counter,
                    )
                else:
                    logger.info("Updated %s classical jobs.", updated_jobs_counter)

        if update_gpu_jobs:
            updated_jobs_counter = 0
            jobs = Job.objects.filter(status__in=Job.RUNNING_STATUSES, gpu=True)
            for job in jobs:
                if update_job_status(job):
                    updated_jobs_counter += 1

            if updated_jobs_counter != len(jobs):
                logger.info(
                    "Updated %s of %s GPU jobs. Pending: ",
                    updated_jobs_counter,
                    len(jobs),
                    len(jobs) - updated_jobs_counter,
                )
            else:
                logger.info("Updated %s GPU jobs.", updated_jobs_counter)
