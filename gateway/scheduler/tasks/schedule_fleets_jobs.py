"""Schedule Fleets jobs service."""

import json
import logging
from datetime import datetime, timezone

from django.conf import settings

from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from core.config_key import ConfigKey
from core.models import Job, Config, Program
from core.services.job_transitions import JobTransitionService
from core.domain.exceptions.invalid_job_transition_exception import InvalidJobTransitionException
from core.services.runners import RunnerError, RunnerRetryableError
from scheduler.schedule import FleetsJobSubmitter, get_jobs_to_schedule_fair_share
from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from .task import SchedulerTask

logger = logging.getLogger("scheduler.ScheduleFleetsJobs")


class ScheduleFleetsJobs(SchedulerTask):
    """Schedule Fleets (Code Engine) jobs service."""

    def __init__(self, kill_signal: KillSignal, metrics: SchedulerMetrics, submitter: FleetsJobSubmitter | None = None):
        self.kill_signal = kill_signal
        self.metrics = metrics
        self.submitter = submitter or FleetsJobSubmitter(JobTransitionService())

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

    def _schedule_jobs_if_slots_available(self, max_slots_possible: int, number_of_slots_running: int):
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

        skipped_regions: set[str | None] = set()
        # The regions in skipped_regions because their breaker is open. The others are there after a retryable
        # failure (a 429, for one) with the breaker still closed, and those jobs are not counted as held by a breaker.
        paused_regions: set[str | None] = set()
        submitted = 0
        for job in jobs:
            if self.kill_signal.received:
                return
            if job.ce_region in skipped_regions:
                if job.ce_region in paused_regions:
                    self.metrics.increment_fleets_jobs_skipped_by_breaker(job.ce_region)
                continue
            if self.submitter.paused(job.ce_region):
                logger.warning("Fleets submits to region %s are paused by the circuit breaker.", job.ce_region)
                skipped_regions.add(job.ce_region)
                paused_regions.add(job.ce_region)
                self.metrics.increment_fleets_jobs_skipped_by_breaker(job.ce_region)
                continue

            env = json.loads(job.env_vars)
            ctx = TraceContextTextMapPropagator().extract(carrier=env)

            try:
                self.submitter.submit(job, ctx)
            except RunnerRetryableError as ex:
                logger.warning("job_id=%s region=%s Job kept QUEUED: %s", job.id, job.ce_region, ex)
                skipped_regions.add(job.ce_region)
                continue
            except (RunnerError, InvalidJobTransitionException):
                # submit() logged why and left the row in its final state
                continue

            submitted += 1
            self.add_queue_wait_time_metric(job)

        self.metrics.increment_task_items(self.name, submitted)
        if submitted:
            logger.info("%s jobs are scheduled for execution.", submitted)

    def add_queue_wait_time_metric(self, job: Job):
        """Add queue wait time metric."""
        if job.filler:
            # Filler jobs skip the queue by design; one that reaches here was
            # rescued from QUEUED by fair-share, and its wait says nothing about
            # how long real work waits.
            return
        now = datetime.now(timezone.utc)
        wait_seconds = (now - job.created).total_seconds()
        job_compute_type = "gpu" if job.gpu else "cpu"
        self.metrics.observe_queue_wait_time(wait_seconds, job_compute_type)
