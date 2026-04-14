"""Schedule queued jobs service."""

import json
import logging
import time
from datetime import datetime, timezone

from django.conf import settings
from django.db.models import Count

from concurrency.exceptions import RecordModifiedError

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

        self._update_job_status_counts_metric()
        self._schedule_fleets_jobs()
        self._schedule_cpu_jobs()
        self._schedule_gpu_jobs()

    def _schedule_fleets_jobs(self):
        """Schedule Fleets jobs (Code Engine). These don't use Ray clusters."""
        max_fleets = settings.LIMITS_MAX_FLEETS
        running_fleets = Job.objects.filter(status__in=Job.RUNNING_STATUSES, runner=Program.FLEETS).count()
        self._schedule_jobs_if_slots_available(
            max_fleets, running_fleets, gpu_job=False, runner=Program.FLEETS, max_limit=max_fleets
        )

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

    def _schedule_jobs_if_slots_available(  # pylint: disable=too-many-branches
        self,
        max_slots_possible,
        number_of_slots_running,
        gpu_job,
        runner=Program.RAY,
        max_limit=100,
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

        jobs = get_jobs_to_schedule_fair_share(slots=free_slots, gpu=gpu_job, runner=runner, max_limit=max_limit)

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

                backup_status = job.status
                backup_logs = job.logs
                backup_resource = job.compute_resource
                backup_ray_job_id = job.ray_job_id
                backup_fleet_id = job.fleet_id
                backup_fleet_id = job.fleet_id

                succeed = False
                attempts = settings.RAY_SETUP_MAX_RETRIES
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
                        if job.status == Job.PENDING:
                            self.add_queue_wait_time_metric(job)

                    except RecordModifiedError:
                        logger.warning("job_id=%s RecordModifiedError sleep 1", job.id)

                        time.sleep(1)

                        job.refresh_from_db()
                        job.status = backup_status
                        job.logs = backup_logs
                        job.compute_resource = backup_resource
                        job.ray_job_id = backup_ray_job_id
                        job.fleet_id = backup_fleet_id
                        job.fleet_id = backup_fleet_id

                retries = settings.RAY_SETUP_MAX_RETRIES - attempts
                if succeed:
                    logger.warning(
                        "job_id=%s Job saved with status=%s (%.2fs) tries=%s",
                        job.id,
                        job.status,
                        time.monotonic() - t1,
                        retries,
                    )
                else:
                    logger.warning(
                        "job_id=%s Job save failed after %s tries (%.2fs)",
                        job.id,
                        retries,
                        time.monotonic() - t1,
                    )
        if jobs:
            logger.info("%s jobs are scheduled for execution.", len(jobs))

    def _update_job_status_counts_metric(self):
        """Update job counts per status and provider (active states only)."""
        statuses = [Job.QUEUED, Job.PENDING, Job.RUNNING]
        rows = (
            Job.objects.filter(status__in=statuses)
            .values("status", "program__provider__name")
            .annotate(count=Count("id"))
        )
        counts = {}
        for row in rows:
            status = row["status"]
            provider = row["program__provider__name"] or "custom"
            counts[(status, provider)] = row["count"]
        self.metrics.clear_job_status_counts()
        for (status, provider), count in counts.items():
            self.metrics.set_job_status_count(count, status, provider)

    def add_queue_wait_time_metric(self, job: Job):
        """Add queue wait time metric."""
        # Wait time can be get from db -> wait_time = RUNNING event.timestamp - QUEUED event.timestamp
        # Jobs are created in QUEUED state, so "created" field should have the same timestamp as QUEUED event
        now = datetime.now(timezone.utc)
        wait_seconds = (now - job.created).total_seconds()
        job_compute_type = "gpu" if job.gpu else "cpu"
        self.metrics.observe_queue_wait_time(wait_seconds, job_compute_type)
