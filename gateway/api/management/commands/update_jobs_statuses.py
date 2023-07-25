"""Cleanup resources command."""
import logging

from django.core.management.base import BaseCommand

from api.models import Job
from api.ray import kill_ray_cluster, get_job_handler
from api.utils import ray_job_status_to_model_job_status

logger = logging.getLogger("commands")


class Command(BaseCommand):
    """Update status of jobs."""

    help = "Update running job statuses and logs."

    def handle(self, *args, **options):
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

                if not success:
                    kill_ray_cluster(job.compute_resource.title)
                    job.compute_resource.delete()
                    job.compute_resource = None
                    job_status = Job.FAILED
                    job.logs = (
                        f"{job.logs}\nSomething went wrong during updating job status."
                    )

                if job_status != job.status:
                    logger.info(
                        "Job [%s] status changed from [%s] to [%s]",
                        job.id,
                        job.status,
                        job_status,
                    )
                    updated_jobs_counter += 1
                # cleanup env vars
                if job.status in Job.TERMINAL_STATES:
                    job.env_vars = "{}"
                job.status = job_status
                job.save()
            else:
                logger.warning(
                    "Job [%s] does not have compute resource associated with it. Skipping.",
                    job.id,
                )

        logger.info("Updated %s jobs.", updated_jobs_counter)
