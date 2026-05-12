"""Schedule queued jobs service."""

import json
import logging
import time
from datetime import datetime, timezone

from django.conf import settings
from django.db.models import F

from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from core.config_key import ConfigKey
from core.models import ComputeResource, Job, JobEvent, Config, Program
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from scheduler.schedule import (
    get_jobs_to_schedule_fair_share,
    execute_job,
)

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from .task import SchedulerTask

logger = logging.getLogger("scheduler.ScheduleQueuedJobs")


class ScheduleQueuedJobs(SchedulerTask):
    """Schedule jobs service."""

    def __init__(self, kill_signal: KillSignal, metrics: SchedulerMetrics):
        self.kill_signal = kill_signal
        self.metrics = metrics

    def run(self):
        """Schedule queued jobs to available cluster slots."""
        if Config.get_bool(ConfigKey.MAINTENANCE):
            logger.warning("System in maintenance mode. Skipping new jobs schedule.")
            return

        self._schedule_fleets_jobs()
        self._schedule_cpu_jobs()
        self._schedule_gpu_jobs()

    def _schedule_fleets_jobs(self):
        """Schedule Fleets jobs (Code Engine). These don't use Ray clusters."""
        max_fleets = settings.LIMITS_MAX_FLEETS
        running_fleets = Job.objects.filter(status__in=Job.RUNNING_STATUSES, runner=Program.FLEETS).count()
        self._schedule_jobs_if_slots_available(max_fleets, running_fleets, gpu_job=False, runner=Program.FLEETS)

    def _schedule_cpu_jobs(self):
        """Schedule CPU jobs."""
        max_clusters = settings.LIMITS_MAX_CLUSTERS
        running_clusters = ComputeResource.objects.filter(active=True, gpu=False).count()
        self._schedule_jobs_if_slots_available(max_clusters, running_clusters, gpu_job=False)

    def _schedule_gpu_jobs(self):
        """Schedule GPU jobs."""
        max_clusters = settings.LIMITS_GPU_CLUSTERS
        running_clusters = ComputeResource.objects.filter(active=True, gpu=True).count()
        self._schedule_jobs_if_slots_available(max_clusters, running_clusters, gpu_job=True)

    def _schedule_jobs_if_slots_available(
        self,
        max_slots_possible,
        number_of_slots_running,
        gpu_job,
        runner=Program.RAY,
    ):
        """Schedule jobs depending on free slots."""
        free_slots = max_slots_possible - number_of_slots_running

        if gpu_job:
            logger.info("%s free GPU cluster slots.", free_slots)
        else:
            logger.info("%s free CPU cluster slots.", free_slots)

        if free_slots < 1:
            logger.info(
                "No slots available. Resource consumption: %s / %s",
                number_of_slots_running,
                max_slots_possible,
            )
            return

        jobs = get_jobs_to_schedule_fair_share(slots=free_slots, gpu=gpu_job, runner=runner)

        for job in jobs:
            if self.kill_signal.received:
                return

            env = json.loads(job.env_vars)
            ctx = TraceContextTextMapPropagator().extract(carrier=env)

            tracer = trace.get_tracer("scheduler.tracer")
            with tracer.start_as_current_span("scheduler.handle", context=ctx):
                t0 = time.monotonic()
                job = execute_job(job)  # from QUEUED to PENDING
                logger.info(
                    "job_id=%s Execute job (%.2fs)",
                    job.id,
                    time.monotonic() - t0,
                )

                t1 = time.monotonic()
                Job.objects.filter(pk=job.id).update(
                    status=job.status,
                    ray_job_id=job.ray_job_id,
                    compute_resource=job.compute_resource,
                    fleet_id=job.fleet_id,
                    version=F("version") + 1,
                )
                job.refresh_from_db(fields=["version"])
                JobEvent.objects.add_status_event(
                    job_id=job.id,
                    origin=JobEventOrigin.SCHEDULER,
                    context=JobEventContext.SCHEDULE_JOBS,
                    status=job.status,
                )

                if job.status == Job.PENDING:
                    self.add_queue_wait_time_metric(job)

                logger.warning(
                    "job_id=%s Job saved with status=%s (%.2fs)",
                    job.id,
                    job.status,
                    time.monotonic() - t1,
                )

        if jobs:
            logger.info("%s jobs are scheduled for execution.", len(jobs))

    def add_queue_wait_time_metric(self, job: Job):
        """Add queue wait time metric."""
        now = datetime.now(timezone.utc)
        wait_seconds = (now - job.created).total_seconds()
        job_compute_type = "gpu" if job.gpu else "cpu"
        self.metrics.observe_queue_wait_time(wait_seconds, job_compute_type)
