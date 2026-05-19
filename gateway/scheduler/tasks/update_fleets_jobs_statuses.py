"""Update Fleets jobs statuses service."""

import logging
from datetime import datetime, timedelta, timezone
from typing import cast

from django.conf import settings

from core.models import Job, JobEvent, Program
from core.services.runners import get_runner, RunnerError, FleetsRunner
from core.model_managers.job_events import JobEventContext, JobEventOrigin

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from .task import SchedulerTask

logger = logging.getLogger("scheduler.UpdateFleetsJobsStatuses")


class UpdateFleetsJobsStatuses(SchedulerTask):
    """Update status of Fleets (Code Engine) jobs."""

    def __init__(self, kill_signal: KillSignal, metrics: SchedulerMetrics):
        self.kill_signal = kill_signal
        self.metrics = metrics

    def update_job_status(self, job: Job) -> bool:
        """Update status of one Fleets job. Returns True if status changed."""
        if not job.fleet_id:
            logger.warning("job_id=%s Fleets job doesn't have fleet_id.", job.id)
            return False

        runner: FleetsRunner = cast(FleetsRunner, get_runner(job))

        try:
            new_status = runner.status()
        except RunnerError as ex:
            logger.error(
                "job_id=%s user_id=%s error=%s Error getting status, set job as FAILED", job.id, job.author.id, str(ex)
            )
            self.to_terminal(job, Job.FAILED)
            return False

        if new_status == Job.SUCCEEDED:
            self.to_terminal(job, Job.SUCCEEDED)
            self._record_execution_duration(job)

        elif new_status == Job.STOPPED:
            self.to_terminal(job, Job.STOPPED)

        elif new_status == Job.FAILED:
            self.to_terminal(job, Job.FAILED)

        elif new_status == Job.PENDING:
            # don't change the status... job still trying to start
            self.stop_job_if_timeout(job)

        elif new_status == Job.RUNNING:
            if job.status == Job.PENDING:
                # Transition from PENDING to RUNNING
                self.to_running(job)

            self.stop_job_if_timeout(job)

        else:
            self.to_terminal(job, Job.FAILED)
            logger.error(
                "job_id=%s user_id=%s status=%s Unknown new job status: %s",
                job.id,
                job.author.id,
                job.status,
                new_status,
            )

        return True

    def to_terminal(self, job: Job, new_status: str) -> None:
        """Persist a terminal status transition."""
        logger.info(
            "job_id=%s user_id=%s Changing status from %s to %s",
            job.id,
            job.author.id,
            job.status,
            new_status,
        )
        job.update_fields({"status": new_status, "sub_status": None, "env_vars": "{}"})
        JobEvent.objects.add_status_event(
            job_id=job.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.UPDATE_JOB_STATUS,
            status=job.status,
        )
        self._increment_terminal_counter(job)

    def to_running(self, job: Job) -> None:
        """Transition job from PENDING to RUNNING."""
        logger.info(
            "job_id=%s user_id=%s Changing status from %s to %s",
            job.id,
            job.author.id,
            job.status,
            Job.RUNNING,
        )
        job.update_fields({"status": Job.RUNNING})
        JobEvent.objects.add_status_event(
            job_id=job.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.UPDATE_JOB_STATUS,
            status=job.status,
        )

    def stop_job_if_timeout(self, job: Job) -> None:
        """Stop job if it has exceeded the maximum allowed duration."""
        timeout = settings.PROGRAM_TIMEOUT
        latest_event = JobEvent.objects.filter(job=job).order_by("-created").first()
        reference_time = latest_event.created if latest_event else job.created
        endtime = reference_time + timedelta(hours=timeout)
        if datetime.now(tz=endtime.tzinfo) < endtime:
            return

        logger.warning("job_id=%s user_id=%s timeout=%s hours: job stopped.", job.id, job.author.id, timeout)
        self.to_terminal(job, Job.STOPPED)

    def _increment_terminal_counter(self, job: Job) -> None:
        """Increment terminal jobs counter."""
        provider = job.program.provider.name if job.program_id and job.program.provider_id else "custom"
        self.metrics.increment_jobs_terminal(provider=provider, final_status=job.status)

    def _record_execution_duration(self, job: Job) -> None:
        """Record execution duration for a successfully completed job."""
        running_event = JobEvent.objects.filter(job=job, data__status=Job.RUNNING).order_by("-created").first()
        if running_event is None:
            return
        duration = (datetime.now(timezone.utc) - running_event.created).total_seconds()
        provider = job.program.provider.name if job.program_id and job.program.provider_id else "custom"
        self.metrics.observe_job_execution_duration(duration, provider)

    def run(self):
        """Update statuses of all running Fleets jobs."""
        if settings.LIMITS_MAX_FLEETS <= 0:
            return

        counter = 0
        # Note: with LIMITS_MAX_FLEETS potentially reaching 1000+ concurrent jobs, updating statuses
        # sequentially will become a bottleneck. This loop should be parallelized using multiple
        # threads or batched processing for performance reasons.
        jobs = Job.objects.filter(status__in=Job.RUNNING_STATUSES, runner=Program.FLEETS)
        for job in jobs:
            if self.kill_signal.received:
                return
            if self.update_job_status(job):
                counter += 1

        if counter:
            logger.info("Updated %s Fleets jobs.", counter)
