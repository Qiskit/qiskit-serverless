"""Cleanup resources command."""

import logging

from concurrency.exceptions import RecordModifiedError
from django.core.management.base import BaseCommand

from api.models import Job
from api.ray import get_job_handler
from api.schedule import (
    check_job_timeout,
    handle_job_status_not_available,
    fail_job_insufficient_resources,
)
from api.utils import ray_job_status_to_model_job_status, check_logs

logger = logging.getLogger("commands")


class Command(BaseCommand):
    """Update status of jobs."""

    help = "Update running job statuses and logs."

    def handle(self, *args, **options):
        # update job statuses
        # pylint: disable=too-many-branches
        updated_jobs_counter = 0
        jobs = Job.objects.filter(status__in=Job.RUNNING_STATES)
        for job in jobs:
            if job.compute_resource:
                job_status = Job.PENDING
                success = True
                job_handler = get_job_handler(job.compute_resource.host)
                if job_handler:
                    ray_job_status = job_handler.status(job.ray_job_id)
                    if ray_job_status:
                        job_status = ray_job_status_to_model_job_status(ray_job_status)
                    else:
                        success = False
                else:
                    success = False

                job_status = check_job_timeout(job, job_status)
                if not success:
                    job_status = handle_job_status_not_available(job, job_status)

                if job_status != job.status:
                    logger.info(
                        "Job [%s] of [%s] changed from [%s] to [%s]",
                        job.id,
                        job.author,
                        job.status,
                        job_status,
                    )
                    updated_jobs_counter += 1
                    job.status = job_status
                    # cleanup env vars
                    if job.in_terminal_state():
                        job.env_vars = "{}"

                if job_handler:
                    logs = job_handler.logs(job.ray_job_id)
                    job.logs = check_logs(logs, job)
                # check if job is resource constrained
                no_resources_log = (
                    "No available node types can fulfill resource request"
                )
                if no_resources_log in logs:
                    job_status = fail_job_insufficient_resources(job)
                    job.status = job_status
                    # cleanup env vars
                    job.env_vars = "{}"

                try:
                    job.save()
                except RecordModifiedError:
                    logger.warning(
                        "Job[%s] record has not been updated due to lock.", job.id
                    )

            else:
                logger.warning(
                    "Job [%s] does not have compute resource associated with it. Skipping.",
                    job.id,
                )

        logger.info("Updated %s jobs.", updated_jobs_counter)
