"""Free resources service."""

import logging

from django.conf import settings
from kubernetes import client as kubernetes_client, config
from kubernetes.dynamic.client import DynamicClient

from core.models import ComputeResource, Job
from core.services.runners import get_runner

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.tasks.task import SchedulerTask

logger = logging.getLogger("scheduler.FreeResources")


class FreeResources(SchedulerTask):
    """Cleanup resources."""

    def __init__(self, kill_signal: KillSignal = None, metrics: SchedulerMetrics = None):
        self.kill_signal = kill_signal or KillSignal()
        self.metrics = metrics or SchedulerMetrics()

    def run(self):
        """Free unused compute resources.
        Input = TERMINAL JOB with ComputeResource.active = True
        Output = TERMINAL JOB with ComputeResource.active = False
        """
        self._free_active_compute_resources()
        self._log_compute_resources_without_job()
        self._log_orphan_clusters()

    def _free_active_compute_resources(self):
        """Free unused compute resources (ComputeResource active with terminal jobs)."""

        jobs_to_free = Job.objects.filter(
            status__in=Job.TERMINAL_STATUSES, compute_resource__active=True
        ).select_related("compute_resource")

        for job in jobs_to_free:
            if self.kill_signal.received:
                return
            self._free_job(job)

    def _free_job(self, job):
        compute_resource = job.compute_resource
        runner_client = get_runner(job)
        success = runner_client.free_resources()
        if success:
            compute_resource.active = False
            compute_resource.save()
            logger.info(
                "[_free_job] job_id=%s cluster=%s Cluster killed",
                job.id,
                compute_resource.title,
            )
        else:
            logger.error(
                "[_free_job] job_id=%s cluster=%s Failed to kill cluster",
                job.id,
                compute_resource.title,
            )

    def _log_compute_resources_without_job(self):
        """Log compute resources without job."""

        # Active ComputeResources with no job at all
        orphan_db_resources = ComputeResource.objects.filter(active=True, job__isnull=True).values_list(
            "title", flat=True
        )
        if orphan_db_resources:
            logger.warning(
                "[_log_compute_resources_without_job] Orphaned ComputeResources with no job: %s",
                sorted(orphan_db_resources),
            )

    def _log_orphan_clusters(self):
        """Log Ray clusters without a ComputeResource."""
        if settings.RAY_CLUSTER_MODE_LOCAL:
            return

        k8s_cluster_names = self._get_k8s_cluster_names(settings.RAY_KUBERAY_NAMESPACE)
        if k8s_cluster_names is None:
            return

        compute_resources_in_k8s = dict(
            ComputeResource.objects.filter(title__in=k8s_cluster_names).values_list("title", "active")
        )
        # ComputeResources + active False, with a real RayCluster in k8s
        orphaned = k8s_cluster_names - set(compute_resources_in_k8s.keys())
        if orphaned:
            logger.error(
                "[_free_orphan_clusters] Orphan k8s clusters found without ComputeResource: %s",
                sorted(orphaned),
            )

        compute_resources_in_k8s_inactive = {t for t, active in compute_resources_in_k8s.items() if not active}
        if compute_resources_in_k8s_inactive:
            logger.error(
                "[_free_orphan_clusters] k8s clusters found with inactive ComputeResource: %s",
                sorted(compute_resources_in_k8s_inactive),
            )

    def _get_k8s_cluster_names(self, namespace) -> set | None:
        """Get RayCluster names from K8s. Returns None if K8s is unavailable."""
        try:
            config.load_incluster_config()
            k8s_client = kubernetes_client.api_client.ApiClient()
            dyn_client = DynamicClient(k8s_client)
            raycluster_client = dyn_client.resources.get(api_version="v1", kind="RayCluster")
            k8s_clusters = raycluster_client.get(namespace=namespace)
            return {item.metadata.name for item in k8s_clusters.items}
        except Exception as ex:  # pylint: disable=broad-exception-caught
            logger.warning("[_free_orphan_clusters] Could not list RayClusters from K8s: %s", ex)
            return None
