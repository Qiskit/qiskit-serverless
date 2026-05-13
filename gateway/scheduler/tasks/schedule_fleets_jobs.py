"""Schedule Fleets jobs service."""

import json
import logging
from datetime import datetime, timezone

from django.conf import settings

from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from core.config_key import ConfigKey
from core.models import Job, Config, Program
from scheduler.schedule import get_jobs_to_schedule_fair_share, execute_fleets
from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from .task import SchedulerTask

logger = logging.getLogger("scheduler.ScheduleFleetsJobs")


class ScheduleFleetsJobs(SchedulerTask):
    """Schedule Fleets (Code Engine) jobs service."""

    def __init__(self, kill_signal: KillSignal, metrics: SchedulerMetrics):
        self.kill_signal = kill_signal
        self.metrics = metrics

    def run(self):
        """Schedule queued Fleets jobs."""
        if Config.get_bool(ConfigKey.MAINTENANCE):
            logger.warning("System in maintenance mode. Skipping new jobs schedule.")
            return

        self._schedule_fleets_jobs()

    def _schedule_fleets_jobs(self):
        """Schedule Fleets jobs (Code Engine). No CPU/GPU distinction."""
        max_fleets = settings.LIMITS_MAX_FLEETS
        running_fleets = Job.objects.filter(status__in=Job.RUNNING_STATUSES, runner=Program.FLEETS).count()
        self._schedule_jobs_if_slots_available(max_fleets, running_fleets)

    def _schedule_jobs_if_slots_available(self, max_slots_possible, number_of_slots_running):
        """Schedule Fleets jobs depending on free slots."""
        free_slots = max_slots_possible - number_of_slots_running

        logger.info("%s free Fleets slots.", free_slots)

        if free_slots < 1:
            logger.info(
                "No slots available. Resource consumption: %s / %s",
                number_of_slots_running,
                max_slots_possible,
            )
            return

        jobs = get_jobs_to_schedule_fair_share(slots=free_slots, gpu=False, runner=Program.FLEETS)

        for job in jobs:
            if self.kill_signal.received:
                return

            env = json.loads(job.env_vars)
            ctx = TraceContextTextMapPropagator().extract(carrier=env)

            job = execute_fleets(job, ctx)

            if job.status == Job.PENDING:
                self.add_queue_wait_time_metric(job)
            logger.warning("job_id=%s Job saved with status=%s", job.id, job.status)

        if jobs:
            logger.info("%s jobs are scheduled for execution.", len(jobs))

    def add_queue_wait_time_metric(self, job: Job):
        """Add queue wait time metric."""
        now = datetime.now(timezone.utc)
        wait_seconds = (now - job.created).total_seconds()
        job_compute_type = "gpu" if job.gpu else "cpu"
        self.metrics.observe_queue_wait_time(wait_seconds, job_compute_type)
