"""Free resources service."""

import logging

from django.conf import settings

from core.models import ComputeResource, Job
from core.services.runners import get_runner

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.tasks.task import SchedulerTask

logger = logging.getLogger("scheduler.FreeResources")


class FreeResources(SchedulerTask):
    """Cleanup resources."""

    def __init__(self, kill_signal: KillSignal, metrics: SchedulerMetrics):
        self.kill_signal = kill_signal
        self.metrics = metrics

    def run(self):
        """Free unused compute resources."""
        if settings.RAY_CLUSTER_NO_DELETE_ON_COMPLETE:
            logger.debug(
                "RAY_CLUSTER_NO_DELETE_ON_COMPLETE is enabled, so compute resources will not be removed.",
            )
            return

        compute_resources = ComputeResource.objects.filter(active=True)
        for compute_resource in compute_resources:
            if self.kill_signal.received:
                return

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

        terminated_job = Job.objects.filter(status__in=Job.TERMINAL_STATUSES, compute_resource=compute_resource).first()
        if terminated_job is None:
            logger.error(
                "compute_resource=%s doesn't have a terminated job linked",
                compute_resource.title,
            )
            return

        is_gpu = terminated_job.gpu
        should_remove_as_classical = remove_classical_jobs and not is_gpu
        should_remove_as_gpu = remove_gpu_jobs and is_gpu
        if should_remove_as_classical or should_remove_as_gpu:
            runner_client = get_runner(terminated_job)
            success = runner_client.free_resources()
            if success:
                compute_resource.active = False
                compute_resource.save()
                logger.info(
                    "job_id=%s compute_resource=%s type=%s Cluster removed ok",
                    terminated_job.id,
                    compute_resource.title,
                    "gpu" if is_gpu else "classical",
                )
            else:
                logger.warning(
                    "job_id=%s compute_resource=%s type=%s Error removing cluster",
                    terminated_job.id,
                    compute_resource.title,
                    "gpu" if is_gpu else "classical",
                )
