"""Cleanup resources command."""
import logging
import time

from django.core.management.base import BaseCommand
from ray.dashboard.modules.job.sdk import JobSubmissionClient

from api.models import Job
from api.utils import ray_job_status_to_model_job_status
from api.ray import kill_ray_cluster


logger = logging.getLogger("commands")


class Command(BaseCommand):
    """Update status of jobs."""

    help = "Update running job statuses and logs."

    def handle(self, *args, **options):
        # update job statuses
        updated_jobs_counter = 0
        for job in Job.objects.filter(status__in=Job.RUNNING_STATES):
            if job.compute_resource:
                success = False
                ray_job_status = Job.PENDING
                retries_left = 10
                while not success and retries_left > 0:
                    try:
                        ray_client = JobSubmissionClient(job.compute_resource.host)
                        # update job logs
                        job.logs = ray_client.get_job_logs(job.ray_job_id)
                        # update job status
                        ray_job_status = ray_job_status_to_model_job_status(
                            ray_client.get_job_status(job.ray_job_id)
                        )
                        success = True
                    except (ConnectionError, RuntimeError) as runtime_error:
                        logger.error(
                            "Runtime error during job status update: %s", runtime_error
                        )
                        retries_left -= 1
                        logger.error("Retries left %s", retries_left)
                        time.sleep(1)

                if not success:
                    kill_ray_cluster(job.compute_resource.title)
                    job.compute_resource.delete()
                    job.compute_resource = None
                    ray_job_status = Job.FAILED
                    job.logs = (
                        f"{job.logs}\nSomething went wrong during updating job status."
                    )

                if ray_job_status != job.status:
                    logger.info(
                        "Job [%s] status changed from [%s] to [%s]",
                        job.id,
                        job.status,
                        ray_job_status,
                    )
                    updated_jobs_counter += 1
                # cleanup env vars
                if job.status in Job.TERMINAL_STATES:
                    job.env_vars = "{}"
                job.status = ray_job_status
                job.save()
            else:
                logger.warning(
                    "Job [%s] does not have compute resource associated with it. Skipping.",
                    job.id,
                )

        logger.info("Updated %s jobs.", updated_jobs_counter)
