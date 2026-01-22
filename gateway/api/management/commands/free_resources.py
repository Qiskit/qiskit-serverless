"""Cleanup resources command."""

import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from api.models import ComputeResource, Job
from api.ray import kill_ray_cluster
from api.repositories.users import UserRepository
from api.services.storage.enums.working_dir import WorkingDir
from api.services.storage.logs_storage import LogsStorage
from api.use_cases.jobs.get_compute_resource_logs import (
    GetComputeResourceLogsUseCase,
    LogsResponse,
)

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

        self.save_logs_to_storage(job=terminated_job)
        terminated_job.logs = ""

        is_gpu = terminated_job.gpu
        should_remove_as_classical = remove_classical_jobs and not is_gpu
        should_remove_as_gpu = remove_gpu_jobs and is_gpu
        if should_remove_as_classical or should_remove_as_gpu:
            success = kill_ray_cluster(compute_resource.title)
            if success:
                # deactivate
                compute_resource.active = False
                compute_resource.save()
                logger.info(
                    "[%s] Cluster [%s] is free after usage from [%s]",
                    "GPU" if is_gpu else "Classical",
                    compute_resource.title,
                    compute_resource.owner,
                )

    def save_logs_to_storage(self, job: Job):
        """
        Save the logs in the corresponding storages.

        Args:
            job: Job
        """

        print(f"save_logs_to_storage:: Job: {job.id}")
        logs = GetComputeResourceLogsUseCase().execute(job)

        user_repository = UserRepository()
        author = user_repository.get_or_create_by_id(job.author)
        username = author.username

        if logs.user_logs:
            self._save_logs_with_provider(logs, username, job)
        else:
            self._save_logs_only_user(logs, username, job)

    def _save_logs_only_user(self, logs: LogsResponse, username: str, job: Job):
        """
        Save the logs in the user storage.

        Args:
            full_logs: str
            username: str
            job: Job
        """

        user_logs_storage = LogsStorage(
            username=username,
            working_dir=WorkingDir.USER_STORAGE,
            function_title=job.program.title,
            provider_name=None,
        )

        user_logs_storage.save(job.id, logs.full_logs)

    def _save_logs_with_provider(self, logs: LogsResponse, username: str, job: Job):
        """
        Save the logs in the provide storage and filter
        for public logs only to save them into the user storage.

        Args:
            full_logs: str
            username: str
            job: Job
        """

        user_logs_storage = LogsStorage(
            username=username,
            working_dir=WorkingDir.USER_STORAGE,
            function_title=job.program.title,
            provider_name=None,
        )

        provider_logs_storage = LogsStorage(
            username=username,
            working_dir=WorkingDir.PROVIDER_STORAGE,
            function_title=job.program.title,
            provider_name=job.program.provider.name,
        )

        user_logs_storage.save(job.id, logs.user_logs)

        provider_logs_storage.save(job.id, logs.full_logs)
