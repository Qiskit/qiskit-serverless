"""Cleanup resources command."""
import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from api.models import ComputeResource, Job
from api.ray import kill_ray_cluster


logger = logging.getLogger("commands")


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
            if len(alive_jobs) == 0 and not settings.RAY_CLUSTER_MODE.get("local"):
                kill_ray_cluster(compute_resource.title)
                compute_resource.delete()
                counter += 1
                logger.info(
                    "Cluster [%s] is free after usage from [%s]",
                    compute_resource.title,
                    compute_resource.owner,
                )

        logger.info("Deallocated %s compute resources.", counter)
