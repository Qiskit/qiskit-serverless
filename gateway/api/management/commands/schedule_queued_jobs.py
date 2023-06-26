"""Cleanup resources command."""
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Model

from api.models import ComputeResource
from api.schedule import get_jobs_to_schedule_fair_share, execute_job

User: Model = get_user_model()
logger = logging.getLogger("commands")


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
        logger.info("%s free cluster slots.", free_clusters_slots)

        if free_clusters_slots < 1:
            # no available resources
            logger.info(
                "No clusters available. Resource consumption: %s / %s",
                number_of_clusters_running,
                max_ray_clusters_possible,
            )
        else:
            # we have available resources
            jobs = get_jobs_to_schedule_fair_share(slots=free_clusters_slots)

            for job in jobs:
                # only for local mode
                if settings.RAY_CLUSTER_MODE.get(
                    "local"
                ) and settings.RAY_CLUSTER_MODE.get("ray_local_host"):
                    logger.info("Running in local mode")
                    compute_resource = ComputeResource.objects.filter(
                        host=settings.RAY_CLUSTER_MODE.get("ray_local_host")
                    ).first()
                    if compute_resource is None:
                        compute_resource = ComputeResource(
                            host=settings.RAY_CLUSTER_MODE.get("ray_local_host"),
                            title="Local compute resource",
                            owner=job.author,
                        )
                        compute_resource.save()
                    job.compute_resource = compute_resource
                    job.save()

                job = execute_job(job)
                logger.info("Executing %s", job)

            logger.info("%s are scheduled for execution.", len(jobs))
