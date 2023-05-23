"""Cleanup resources command."""
from django.conf import settings
from django.core.management.base import BaseCommand

from api.models import ComputeResource, Job
from api.ray import kill_ray_cluster


class Command(BaseCommand):
    """Cleanup resources."""

    help = "Clean up resources."

    def handle(self, *args, **options):
        compute_resources = ComputeResource.objects.all()
        counter = 0

        for compute_resource in compute_resources:
            alive_jobs = Job.objects.filter(
                status__in=Job.RUNNING_STATES, compute_resource=compute_resource
            )

            # only kill cluster if not in local mode and no jobs are running there
            if (
                len(alive_jobs) == 0
                and not settings.RAY_CLUSTER_MODE.get("local")
            ):
                kill_ray_cluster(compute_resource.title)
                counter += 1
                self.stdout.write(
                    f"Cluster [{compute_resource.title}] "
                    f"is free after usage from [{compute_resource.users}]"
                )

        self.stdout.write(
            self.style.SUCCESS(f"Deallocated {counter} compute resources.")
        )
