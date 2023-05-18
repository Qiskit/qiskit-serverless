"""Cleanup resources command."""
from django.core.management.base import BaseCommand
from ray.dashboard.modules.job.sdk import JobSubmissionClient

from api.models import ComputeResource, Job
from api.schedule import kill_ray_cluster
from api.utils import ray_job_status_to_model_job_status


class UpdateStatusAndCleanUpResourcesCommand(BaseCommand):
    """Update status of jobs and cleanup resources."""

    help = "Update job statuses and cleans up resources which are not used."

    def handle(self, *args, **options):
        compute_resources = ComputeResource.objects.all()
        counter = 0
        for compute_resource in compute_resources:
            alive_jobs = Job.objects.filter(
                status__in=Job.RUNNING_STATES, compute_resource=compute_resource
            )

            if len(alive_jobs) == 0:
                kill_ray_cluster(compute_resource.title)
                counter += 1
                self.stdout.write(
                    f"Cluster [{compute_resource.title}] "
                    f"is free after usage from [{compute_resource.users}]"
                )

            ray_client = JobSubmissionClient(compute_resource.host)
            for job in alive_jobs:
                ray_job_status = ray_client.get_job_status(job.ray_job_id)
                job.status = ray_job_status_to_model_job_status(ray_job_status)
                job.save()

        self.stdout.write(
            self.style.SUCCESS(f"Deallocated {counter} compute resources.")
        )
