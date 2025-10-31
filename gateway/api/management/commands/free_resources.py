"""Cleanup resources command."""

import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from api.models import ComputeResource, Job
from api.ray import kill_ray_cluster
from main import settings as config


logger = logging.getLogger("commands")


class Command(BaseCommand):
    """Cleanup resources."""

    help = "Clean up resources."

    def handle(self, *args, **options):
        compute_resources = ComputeResource.objects.filter(active=True)

        for compute_resource in compute_resources:
            # I think this logic could be reviewed because now each job
            # would have its own compute resource but let's do that
            # in an additional iteration
            total_alive_jobs = Job.objects.filter(
                status__in=Job.RUNNING_STATUSES, compute_resource=compute_resource
            ).count()

            max_ray_clusters_possible = settings.LIMITS_MAX_CLUSTERS
            max_gpu_clusters_possible = settings.LIMITS_GPU_CLUSTERS
            remove_classical_jobs = int(max_ray_clusters_possible) != 0
            remove_gpu_jobs = int(max_gpu_clusters_possible) != 0

            # only kill cluster if not in local mode and no jobs are running there
            if total_alive_jobs == 0 and not settings.RAY_CLUSTER_MODE.get("local"):
                if config.RAY_CLUSTER_NO_DELETE_ON_COMPLETE:
                    logger.debug(
                        "RAY_CLUSTER_NO_DELETE_ON_COMPLETE is enabled, "
                        + "so cluster [%s] will not be removed",
                        compute_resource.title,
                    )
                    return

                terminated_job = Job.objects.filter(
                    status__in=Job.TERMINAL_STATUSES, compute_resource=compute_resource
                ).first()
                if terminated_job is None:
                    logger.error(
                        "There is no job finished for [%s] compute resource:",
                        compute_resource.title,
                    )
                    return

                # Remove non GPU Compute Resources only if you are managing non GPU jobs
                if remove_classical_jobs and terminated_job.gpu is False:
                    success = kill_ray_cluster(compute_resource.title)
                    if success:
                        # deactivate
                        compute_resource.active = False
                        compute_resource.save()
                        logger.info(
                            "Classical Cluster [%s] is free after usage from [%s]",
                            compute_resource.title,
                            compute_resource.owner,
                        )

                # Remove GPU Compute Resources only if you are managing GPU jobs
                if remove_gpu_jobs and terminated_job.gpu:
                    success = kill_ray_cluster(compute_resource.title)
                    if success:
                        # deactivate
                        compute_resource.active = False
                        compute_resource.save()
                        logger.info(
                            "GPU Cluster [%s] is free after usage from [%s]",
                            compute_resource.title,
                            compute_resource.owner,
                        )
