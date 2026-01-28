"""Cleanup resources command."""

import logging

from concurrency.exceptions import RecordModifiedError
from django.conf import settings
from django.core.management.base import BaseCommand

from api.domain.function import check_logs
from api.domain.function.filter_logs import (
    filter_logs_with_non_public_tags,
    filter_logs_with_public_tags,
    remove_prefix_tags_in_logs,
)
from api.models import Job
from api.ray import get_job_handler, JobHandler
from api.schedule import (
    check_job_timeout,
    handle_job_status_not_available,
    fail_job_insufficient_resources,
)
from api.services.storage.logs_storage import LogsStorage
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
    ray_job_status = job_handler.status(job.ray_job_id) if job_handler else None

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
        # cleanup env vars and save logs when job reaches terminal state
        if job.in_terminal_state():
            job.sub_status = None
            job.env_vars = "{}"
            if job_handler:
                save_logs_to_storage(job, job_handler)

    if job_handler:
        logs = job_handler.logs(job.ray_job_id)
        # check if job is resource constrained
        no_resources_log = "No available node types can fulfill resource request"
        if no_resources_log in logs:
            job_new_status = fail_job_insufficient_resources(job)
            job.status = job_new_status
            # cleanup env vars
            job.env_vars = "{}"

    try:
        job.save()
    except RecordModifiedError:
        logger.warning("Job [%s] record has not been updated due to lock.", job.id)

    return status_has_changed


def save_logs_to_storage(job: Job, job_handler: JobHandler):
    """
    Save the logs in the corresponding storages.

    This function is called exactly once when a job transitions to a terminal state.

    Args:
        job: Job that has reached a terminal state
        job_handler: JobHandler to retrieve logs from Ray
    """
    try:
        logs = job_handler.logs(job.ray_job_id)
        logs = check_logs(logs, job)
    except ConnectionError:
        logger.error(
            "Compute resource [%s] is not accessible for logs. Job [%s]",
            job.compute_resource.title,
            job.id,
        )
        logs = "Error getting logs: compute resource is not accessible."

    logs_storage = LogsStorage(job)
    if job.program.provider:
        public_logs = filter_logs_with_public_tags(logs)
        logs_storage.save_public_logs(public_logs)
        private_logs = filter_logs_with_non_public_tags(logs)
        logs_storage.save_private_logs(private_logs)
    else:
        filtered_logs = remove_prefix_tags_in_logs(logs)
        logs_storage.save_public_logs(filtered_logs)

    logger.info("Logs saved to storage for job [%s]", job.id)


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
