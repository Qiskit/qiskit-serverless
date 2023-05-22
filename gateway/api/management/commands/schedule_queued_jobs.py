"""Cleanup resources command."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Model

from api.models import ComputeResource
from api.schedule import get_jobs_to_schedule_fair_share, execute_job

User: Model = get_user_model()


class Command(BaseCommand):
    """Schedule jobs command."""

    help = (
        "Schedule jobs that are in queued "
        "status based on availability of resources in the system."
    )

    def handle(self, *args, **options):
        max_ray_clusters_possible = settings.LIMITS_MAX_CLUSTERS
        number_of_clusters_running = ComputeResource.objects.count()
        free_clusters_slots = max_ray_clusters_possible - number_of_clusters_running

        if free_clusters_slots < 1:
            # no available resources
            self.stdout.write(
                f"No clusters available. Resource consumption: "
                f"{number_of_clusters_running}/{max_ray_clusters_possible}"
            )
        else:
            # we have available resources
            jobs = get_jobs_to_schedule_fair_share(slots=free_clusters_slots)

            for job in jobs:
                # TODO: check if local mode -> run on single cluster
                if settings.RAY_CLUSTER_MODE.get("local") and settings.RAY_CLUSTER_MODE.get("ray_local_host"):
                    self.stdout.write(self.style.WARNING("Running in local mode"))
                    compute_resource = ComputeResource.objects.filter(host=settings.RAY_CLUSTER_MODE.get("ray_local_host")).first()
                    if compute_resource is None:
                        compute_resource = ComputeResource(
                            host=settings.RAY_CLUSTER_MODE.get("ray_local_host"),
                            title="Local compute resource",
                            owner=job.author
                        )
                        compute_resource.save()
                    job.compute_resource = compute_resource
                    job.save()

                job = execute_job(job)
                self.stdout.write(f"Executing {job}")

            self.stdout.write(
                self.style.SUCCESS(f"{len(jobs)} are scheduled for execution.")
            )
