"""Schedule queued jobs service."""

import json
import logging
import time
from datetime import datetime, timezone

from concurrency.exceptions import RecordModifiedError
from django.conf import settings

from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from core.config_key import ConfigKey
from core.models import ComputeResource, Job, JobEvent, Config
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from scheduler.schedule import (
    get_jobs_to_schedule_fair_share,
    execute_job,
)

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from .task import SchedulerTask

logger = logging.getLogger("ScheduleQueuedJobs")


class ScheduleQueuedJobs(SchedulerTask):
    """Schedule jobs service."""

    def __init__(self, kill_signal: KillSignal = None, metrics: SchedulerMetrics = None):
        self.kill_signal = kill_signal or KillSignal()
        self.metrics = metrics or SchedulerMetrics()

    def run(self):
        """Schedule queued jobs to available cluster slots."""
        if Config.get_bool(ConfigKey.MAINTENANCE):
            logger.warning("System in maintenance mode. Skipping new jobs schedule.")
            return

        self._schedule_cpu_jobs()
        self._schedule_gpu_jobs()

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

    def _schedule_jobs_if_slots_available(self, max_ray_clusters_possible, number_of_clusters_running, gpu_job):
        """Schedule jobs depending on free cluster slots."""
        free_clusters_slots = max_ray_clusters_possible - number_of_clusters_running

        # Store the queue size in the metrics
        self.set_queue_size_metric(gpu_job)

        if gpu_job:
            logger.info("%s free GPU cluster slots.", free_clusters_slots)
        else:
            logger.info("%s free CPU cluster slots.", free_clusters_slots)

        if free_clusters_slots < 1:
            # no available resources
            logger.info(
                "No clusters available. Resource consumption: %s / %s",
                number_of_clusters_running,
                max_ray_clusters_possible,
            )
            return

        jobs = get_jobs_to_schedule_fair_share(slots=free_clusters_slots, gpu=gpu_job)

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

                job_id = job.id
                backup_status = job.status
                backup_logs = job.logs
                backup_resource = job.compute_resource
                backup_ray_job_id = job.ray_job_id

                succeed = False
                attempts = settings.RAY_SETUP_MAX_RETRIES
                retry_count = 0

                t1 = time.monotonic()
                while not succeed and attempts > 0:
                    attempts -= 1

                    try:
                        job.save()
                        # # remove artifact after successful submission and save
                        # if os.path.exists(job.program.artifact.path):
                        #     os.remove(job.program.artifact.path)

                        succeed = True
                        JobEvent.objects.add_status_event(
                            job_id=job.id,
                            origin=JobEventOrigin.SCHEDULER,
                            context=JobEventContext.SCHEDULE_JOBS,
                            status=job.status,
                        )

                        # Store the wait time (from QUEUED to PENDING) in the metrics
                        self.add_queue_wait_time_metric(job)

                    except RecordModifiedError:
                        retry_count += 1
                        logger.warning("job_id=%s RecordModifiedError sleep 1", job.id)

                        time.sleep(1)

                        job = Job.objects.get(id=job_id)
                        job.status = backup_status
                        job.logs = backup_logs
                        job.compute_resource = backup_resource
                        job.ray_job_id = backup_ray_job_id

                logger.info(
                    "job_id=%s Job updated set to PENDING (%.2fs) retries=%s",
                    job.id,
                    time.monotonic() - t1,
                    retry_count,
                )
        if jobs:
            logger.info("%s jobs are scheduled for execution.", len(jobs))

    def set_queue_size_metric(self, gpu_job):
        """Add queue size metric."""
        queue_count = Job.objects.filter(status=Job.QUEUED, gpu=gpu_job).count()
        compute_type = "gpu" if gpu_job else "cpu"
        self.metrics.set_queue_size(queue_count, compute_type)

    def add_queue_wait_time_metric(self, job: Job):
        """Add queue wait time metric."""
        # Wait time can be get from db -> wait_time = RUNNING event.timestamp - QUEUED event.timestamp
        # Jobs are created in QUEUED state, so "created" field should have the same timestamp as QUEUED event
        now = datetime.now(timezone.utc)
        wait_seconds = (now - job.created).total_seconds()
        job_compute_type = "gpu" if job.gpu else "cpu"
        self.metrics.observe_queue_wait_time(wait_seconds, job_compute_type)
