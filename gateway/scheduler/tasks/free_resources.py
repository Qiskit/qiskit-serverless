"""Free resources service."""

import logging

from core.models import Job
from core.services.runners import get_runner

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.tasks.task import SchedulerTask

logger = logging.getLogger("commands")


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
        jobs_to_free = Job.objects.filter(
            status__in=Job.TERMINAL_STATUSES, compute_resource__active=True
        ).select_related("compute_resource")

        for job in jobs_to_free:
            if self.kill_signal.received:
                return
            free_compute_resource(job)


def free_compute_resource(job: Job):
    """Free the compute resource associated with a terminal job."""
    compute_resource = job.compute_resource
    runner_client = get_runner(job)
    success = runner_client.free_resources()
    if success:
        compute_resource.active = False
        compute_resource.save()
        logger.info(
            "Cluster [%s] is free after usage from [%s]. JobID [%s]",
            compute_resource.title,
            compute_resource.owner,
            job.id,
        )
