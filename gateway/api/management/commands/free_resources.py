"""Cleanup resources command."""

import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from api.domain.function import check_logs
from api.domain.function.filter_logs import (
    log_filter_provider_job_public,
    log_filter_user_job,
)
from api.models import ComputeResource, Job
from api.ray import get_job_handler, kill_ray_cluster
from api.services.storage.logs_storage import LogsStorage

logger = logging.getLogger("commands")


class Command(BaseCommand):
    """Cleanup resources."""

    help = "Clean up resources."

    def handle(self, *args, **options):
        if settings.RAY_CLUSTER_NO_DELETE_ON_COMPLETE:
            logger.debug(
                "RAY_CLUSTER_NO_DELETE_ON_COMPLETE is enabled, "
                "so compute resources will not be removed.",
            )
            return

        if settings.RAY_CLUSTER_MODE.get("local"):
            logger.debug(
                "RAY_CLUSTER_MODE is local, "
                "so compute resources will not be removed.",
            )
            compute_resources = ComputeResource.objects.filter(active=True)
            for compute_resource in compute_resources:
                terminated_jobs = Job.objects.filter(
                    status__in=Job.TERMINAL_STATUSES, compute_resource=compute_resource
                )
                for job in terminated_jobs:
                    self.save_logs_to_storage(job=job)
            return

        compute_resources = ComputeResource.objects.filter(active=True)
        for compute_resource in compute_resources:
            # I think this logic could be reviewed because now each job
            # would have its own compute resource but let's do that
            # in an additional iteration
            there_are_alive_jobs = Job.objects.filter(
                status__in=Job.RUNNING_STATUSES, compute_resource=compute_resource
            ).exists()

            # only kill cluster if not in local mode and no jobs are running there
            if not there_are_alive_jobs:
                self.remove_compute_resource(compute_resource)

    def remove_compute_resource(self, compute_resource: ComputeResource):
        """
        This method removes a Compute Resource if it's
        available in the cluster.

        Args:
            compute_resource: ComputeResource
        """
        max_ray_clusters_possible = settings.LIMITS_MAX_CLUSTERS
        max_gpu_clusters_possible = settings.LIMITS_GPU_CLUSTERS
        remove_classical_jobs = max_ray_clusters_possible > 0
        remove_gpu_jobs = max_gpu_clusters_possible > 0

        terminated_job = Job.objects.filter(
            status__in=Job.TERMINAL_STATUSES, compute_resource=compute_resource
        ).first()
        if terminated_job is None:
            logger.error(
                "There is no job finished for [%s] compute resource:",
                compute_resource.title,
            )
            return

        is_gpu = terminated_job.gpu
        should_remove_as_classical = remove_classical_jobs and not is_gpu
        should_remove_as_gpu = remove_gpu_jobs and is_gpu
        if should_remove_as_classical or should_remove_as_gpu:
            self.save_logs_to_storage(job=terminated_job)
            terminated_job.logs = ""

            success = kill_ray_cluster(compute_resource.title)
            if success:
                # deactivate
                compute_resource.active = False
                compute_resource.save()
                logger.info(
                    "[%s] Cluster [%s] is free after usage from [%s]. JobID [%s]",
                    "GPU" if is_gpu else "Classical",
                    compute_resource.title,
                    compute_resource.owner,
                    terminated_job.id,
                )

    def save_logs_to_storage(self, job: Job):
        """
        Save the logs in the corresponding storages.

        Args:
            job: Job
        """

        try:
            job_handler = get_job_handler(job.compute_resource.host)
            logs = job_handler.logs(job.ray_job_id)
            logs = check_logs(logs, job)
        except ConnectionError:
            logger.error(
                "Compute resource [%s] is not accessible for logs. "
                "Skipping `remove_compute_resource` with Job [%s]",
                job.compute_resource.title,
                job.id,
            )
            logs = "Error getting logs: compute resource is not accessible."

        logs_storage = LogsStorage(job)
        if job.program.provider:
            public_logs = log_filter_provider_job_public(logs)
            logs_storage.save_public_logs(public_logs)
            logs_storage.save_private_logs(logs)
        else:
            filtered_logs = log_filter_user_job(logs)
            logs_storage.save_public_logs(filtered_logs)
