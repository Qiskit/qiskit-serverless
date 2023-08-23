"""Cleanup resources command."""
import logging
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand

from api.models import Job
from api.ray import kill_ray_cluster, get_job_handler
from api.utils import ray_job_status_to_model_job_status
from main import settings as config

logger = logging.getLogger("commands")


class Command(BaseCommand):
    """Update status of jobs."""

    help = "Update running job statuses and logs."

    def handle(self, *args, **options):  #  pylint: disable=too-many-branches
        # update job statuses
        updated_jobs_counter = 0
        for job in Job.objects.filter(status__in=Job.RUNNING_STATES):
            if job.compute_resource:
                job_status = Job.PENDING
                success = True
                job_handler = get_job_handler(job.compute_resource.host)
                if job_handler:
                    logs = job_handler.logs(job.ray_job_id)
                    if logs:
                        job.logs = logs

                    ray_job_status = job_handler.status(job.ray_job_id)
                    if ray_job_status:
                        job_status = ray_job_status_to_model_job_status(ray_job_status)
                    else:
                        success = False
                else:
                    success = False

                timeout = config.PROGRAM_TIMEOUT
                if job.updated:
                    endtime = job.updated + timedelta(days=timeout)
                else:
                    endtime = job.created + timedelta(days=timeout)
                now = datetime.now(tz=endtime.tzinfo)
                if endtime < now:
                    job_status = Job.STOPPED
                    job.logs = (
                        f"{job.logs}.\nMaximum job runtime reached. Stopping the job."
                    )
                    logger.warning(
                        "Job [%s] reached maximum runtime [%s] days and stopped.",
                        job.id,
                        timeout,
                    )

                if not success:
                    if config.RAY_CLUSTER_NO_DELETE_ON_COMPLETE:
                        logger.debug(
                            "RAY_CLUSTER_NO_DELETE_ON_COMPLETE is enabled, "
                            + "so cluster [%s] will not be removed",
                            job.compute_resource.title,
                        )
                    else:
                        kill_ray_cluster(job.compute_resource.title)
                        job.compute_resource.delete()
                        job.compute_resource = None
                        job_status = Job.FAILED
                        job.logs = f"{job.logs}\nSomething went wrong during updating job status."

                if job_status != job.status:
                    logger.info(
                        "Job [%s] status changed from [%s] to [%s]",
                        job.id,
                        job.status,
                        job_status,
                    )
                    updated_jobs_counter += 1
                    # cleanup env vars
                    if job.in_terminal_state():
                        job.env_vars = "{}"
                    job.status = job_status
                    job.save()
            else:
                logger.warning(
                    "Job [%s] does not have compute resource associated with it. Skipping.",
                    job.id,
                )

        logger.info("Updated %s jobs.", updated_jobs_counter)
