"""Cleanup resources command."""

import logging

from concurrency.exceptions import RecordModifiedError
from django.core.management.base import BaseCommand

from api.domain.function.filter_logs import (
    filter_logs_with_non_public_tags,
    filter_logs_with_public_tags,
    remove_prefix_tags_in_logs,
)
from core.config_key import ConfigKey
from core.models import Job, JobEvent, Config
from core.services.ray import get_job_handler
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from core.utils import check_logs, ray_job_status_to_model_job_status
from scheduler.schedule import (
    check_job_timeout,
    handle_job_status_not_available,
    fail_job_insufficient_resources,
)
from api.services.storage.logs_storage import LogsStorage

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
        logger.warning("Job [%s] marked as FAILED because Ray get_job_status: %s", job.id, str(ex))
        job.status = Job.FAILED
        job.sub_status = None
        job.env_vars = "{}"
        try:
            job.save()
            JobEvent.objects.add_status_event(
                job_id=job.id,
                origin=JobEventOrigin.SCHEDULER,
                context=JobEventContext.UPDATE_JOB_STATUS,
                status=job.status,
            )
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
        # cleanup env vars and save logs when job reaches terminal state
        if job.in_terminal_state():
            job.sub_status = None
            job.env_vars = "{}"
            logs = job_handler.logs(job.ray_job_id) if job_handler else ""
            save_logs_to_storage(job, logs)
            job.logs = ""

    if job_handler:
        logs = job_handler.logs(job.ray_job_id)
        # check if job is resource constrained
        no_resources_log = "No available node types can fulfill resource request"
        if no_resources_log in logs:
            job_new_status = fail_job_insufficient_resources(job)
            logs = (
                "Insufficient resources available to the run job in this "
                "configuration.\nMax resources allowed are "
                f"{Config.get_int(ConfigKey.LIMITS_CPU_PER_TASK)} CPUs and "
                f"{Config.get_int(ConfigKey.LIMITS_MEMORY_PER_TASK)} GB of RAM per job."
            )
            job.status = job_new_status
            # cleanup env vars
            job.env_vars = "{}"
            status_has_changed = True
            save_logs_to_storage(job, logs)
            job.logs = ""

    try:
        job.save()

        if status_has_changed:
            JobEvent.objects.add_status_event(
                job_id=job.id,
                origin=JobEventOrigin.SCHEDULER,
                context=JobEventContext.UPDATE_JOB_STATUS,
                status=job.status,
            )
    except RecordModifiedError:
        logger.warning("Job [%s] record has not been updated due to lock.", job.id)

    return status_has_changed


def save_logs_to_storage(job: Job, logs: str):
    """
    Save the logs in the corresponding storages.

    This function is called exactly once when a job transitions to a terminal state.

    Args:
        job: Job that has reached a terminal state
        job_handler: JobHandler to retrieve logs from Ray
    """

    logs = check_logs(logs, job)

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
        max_ray_clusters_possible = Config.get_int(ConfigKey.LIMITS_CPU_CLUSTERS)
        max_gpu_clusters_possible = Config.get_int(ConfigKey.LIMITS_GPU_CLUSTERS)
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
