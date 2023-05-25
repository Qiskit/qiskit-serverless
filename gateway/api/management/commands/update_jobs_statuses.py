"""Cleanup resources command."""
from django.core.management.base import BaseCommand
from ray.dashboard.modules.job.sdk import JobSubmissionClient

from api.models import Job
from api.utils import ray_job_status_to_model_job_status


class Command(BaseCommand):
    """Update status of jobs."""

    help = "Update running job statuses and logs."

    def handle(self, *args, **options):
        # update job statuses
        updated_jobs_counter = 0
        for job in Job.objects.filter(status__in=Job.RUNNING_STATES):
            if job.compute_resource:
                ray_client = JobSubmissionClient(job.compute_resource.host)
                # update job logs
                job.logs = ray_client.get_job_logs(job.ray_job_id)
                # update job status
                ray_job_status = ray_job_status_to_model_job_status(
                    ray_client.get_job_status(job.ray_job_id)
                )
                if ray_job_status != job.status:
                    self.stdout.write(
                        f"Job [{job.id}] status changed from [{job.status}] to [{ray_job_status}]"
                    )
                    updated_jobs_counter += 1
                # cleanup env vars
                if job.status in Job.TERMINAL_STATES:
                    job.env_vars = "{}"
                job.status = ray_job_status
                job.save()
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"Job [{job.id}] does not have compute resource associated with it."
                        f"Skipping."
                    )
                )

        self.stdout.write(self.style.SUCCESS(f"Updated {updated_jobs_counter} jobs."))
