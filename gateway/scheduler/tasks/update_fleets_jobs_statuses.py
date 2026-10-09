"""Update Fleets jobs statuses service."""

import logging
from datetime import datetime, timedelta, timezone
from typing import cast

from django.conf import settings

from core.models import Job, JobEvent, Program
from core.domain.exceptions.invalid_job_transition_exception import InvalidJobTransitionException
from core.services.job_transitions import JobTransitionService
from core.services.runners import get_runner, RunnerError, RunnerRetryableError, FleetsRunner
from core.model_managers.job_events import JobEventContext, JobEventOrigin

from scheduler.kill_signal import KillSignal
from scheduler.schedule import FleetsJobCanceller, first_cancel_refusal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from .task import SchedulerTask

logger = logging.getLogger("scheduler.UpdateFleetsJobsStatuses")

# A cancel reaches the task store in about 30s, or about 150s if the task had not started.
_STOPPING_DEADLINE_SECONDS = 300


class UpdateFleetsJobsStatuses(SchedulerTask):
    """Update status of Fleets (Code Engine) jobs."""

    def __init__(
        self,
        kill_signal: KillSignal,
        metrics: SchedulerMetrics,
        transitions: JobTransitionService | None = None,
        canceller: FleetsJobCanceller | None = None,
    ):
        self.kill_signal = kill_signal
        self.metrics = metrics
        self.transitions = transitions or JobTransitionService()
        self.canceller = canceller or FleetsJobCanceller(self.transitions)

    def update_job_status(self, job: Job) -> bool:
        """Update status of one Fleets job. Returns True if status changed."""
        if not job.fleet_id:
            if job.status == Job.STOPPING:
                # fleet_id is admin-editable, and the check below never looks again
                self.to_terminal(job, Job.STOPPED)
                return True
            logger.warning("job_id=%s Fleets job doesn't have fleet_id.", job.id)
            return False

        runner: FleetsRunner = cast(FleetsRunner, get_runner(job))

        try:
            new_status = runner.status()
        except (RunnerError, ValueError) as ex:
            # status() raises on configuration and data problems, never on a job that failed: a
            # deleted program, an inactive project, an unconfigured bucket, a bad COS secret.
            logger.error(
                "job_id=%s user_id=%s error=%s Could not read the status, treating it as unknown",
                job.id,
                job.author.id,
                str(ex),
            )
            new_status = None

        if job.status == Job.STOPPING:
            return self.confirm_stop(job, new_status)

        if new_status is None:
            logger.debug("job_id=%s status unknown, bounding the wait", job.id)
            # Without this the job is immortal: no other scheduler task touches a
            # PENDING or RUNNING Fleets job, so a status that never resolves would
            # hold the user's concurrency slot forever.
            return self.stop_job_if_timeout(job)

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

    def confirm_stop(self, job: Job, new_status: str | None) -> bool:
        """End a STOPPING job once the task store reports any terminal task state, or on the deadline.

        No cancel is sent from here: whoever asked for the stop already sent it.
        """
        if new_status in Job.TERMINAL_STATUSES:
            logger.info("job_id=%s stop confirmed, task store reported %s", job.id, new_status)
        else:
            # The earliest STOPPING event, not the latest event of any kind: a job still reporting
            # sub_status would otherwise push its own deadline out for ever.
            stopping_event = JobEvent.objects.filter(job=job, data__status=Job.STOPPING).order_by("created").first()
            reference_time = stopping_event.created if stopping_event else job.updated
            if datetime.now(timezone.utc) - reference_time < timedelta(seconds=_STOPPING_DEADLINE_SECONDS):
                return False
            logger.warning(
                "job_id=%s user_id=%s stop not confirmed after %ss, writing STOPPED anyway.",
                job.id,
                job.author.id,
                _STOPPING_DEADLINE_SECONDS,
            )
        self.to_terminal(job, Job.STOPPED)
        return True

    def to_terminal(self, job: Job, new_status: str) -> None:
        """Persist a terminal status transition."""
        requested = job.status == Job.STOPPING
        logger.info(
            "job_id=%s user_id=%s Changing status from %s to %s",
            job.id,
            job.author.id,
            job.status,
            new_status,
        )
        try:
            self.transitions.to_terminal(
                job,
                new_status,
                origin=JobEventOrigin.SCHEDULER,
                context=JobEventContext.UPDATE_JOB_STATUS,
                job_fields={"sub_status": None, "env_vars": "{}"},
            )
        except InvalidJobTransitionException as ex:
            logger.info("job_id=%s transition rejected from %s, ignoring: %s", job.id, job.status, str(ex))
            return
        self._increment_terminal_counter(job, requested=requested)

    def to_running(self, job: Job) -> None:
        """Transition job from PENDING to RUNNING, or emit an in-progress event if it already is."""
        job_started = job.status == Job.PENDING
        if job_started:
            logger.info(
                "job_id=%s user_id=%s Changing status from %s to %s",
                job.id,
                job.author.id,
                job.status,
                Job.RUNNING,
            )
            try:
                self.transitions.pending_to_running(
                    job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS
                )
            except InvalidJobTransitionException as ex:
                # Lost the race: the job reached a terminal status concurrently (like user stopped the job)
                logger.info("job_id=%s transition rejected from %s, skipping RUNNING: %s", job.id, job.status, str(ex))
        else:
            self.transitions.running_to_running(job)

    def stop_job_if_timeout(self, job: Job) -> bool:
        """Stop a job that has outlived PROGRAM_TIMEOUT. Returns True if it ended the job."""
        if job.filler:
            return False

        timeout = settings.PROGRAM_TIMEOUT
        latest_event = JobEvent.objects.filter(job=job).order_by("-created").first()
        reference_time = latest_event.created if latest_event else job.created
        endtime = reference_time + timedelta(hours=timeout)
        # The paused check is not needed for correctness, cancel() raises anyway. It keeps an open
        # breaker from logging one line per timed-out job per tick.
        if datetime.now(tz=endtime.tzinfo) < endtime or self.canceller.paused(job.ce_region):
            return False

        logger.warning("job_id=%s user_id=%s timeout=%s hours: stopping the job.", job.id, job.author.id, timeout)
        try:
            cancelled = self.canceller.cancel(job, context=JobEventContext.UPDATE_JOB_STATUS)
        except RunnerRetryableError as ex:
            # Nothing is written: STOPPED here would claim a stop that never happened.
            logger.warning("job_id=%s fleet_id=%s cancel not delivered on timeout: %s", job.id, job.fleet_id, str(ex))
            return False
        except RunnerError as ex:
            log = logger.error if first_cancel_refusal(job) else logger.debug
            log("job_id=%s fleet_id=%s cancel refused, the job stays active: %s", job.id, job.fleet_id, str(ex))
            return False
        except InvalidJobTransitionException as ex:
            logger.info("job_id=%s transition rejected, skipping STOPPING: %s", job.id, str(ex))
            return False

        if not cancelled:
            self.to_terminal(job, Job.STOPPED)
        return True

    def _increment_terminal_counter(self, job: Job, *, requested: bool = False) -> None:
        """Increment terminal jobs counter. `requested` means something asked this job to stop."""
        if job.filler:
            # A filler never counts as user demand, so it has its own two counters.
            if requested:
                self.metrics.increment_filler_jobs_stopped()
            else:
                self.metrics.increment_filler_jobs_ended(job.status)
            return
        provider = job.program.provider.name if job.program_id and job.program.provider_id else "custom"
        self.metrics.increment_jobs_terminal(provider=provider, final_status=job.status)

    def _record_execution_duration(self, job: Job) -> None:
        """Record execution duration for a successfully completed job."""
        if job.filler:
            # Filler jobs run until something needs their slot, so their lifetime
            # says nothing about how long real work takes.
            return
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
        jobs = Job.objects.filter(status__in=Job.RUNNING_STATUSES, runner=Program.FLEETS).select_related(
            "author", "program__code_engine_project", "program__provider"
        )
        for job in jobs:
            if self.kill_signal.received:
                logger.info("Kill signal received, stopping status update cycle")
                return
            try:
                if self.update_job_status(job):
                    counter += 1
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception(
                    "job_id=%s Failed to publish event, skipping DB update — will retry next iteration", job.id
                )

        if counter:
            logger.info("Updated %s Fleets jobs.", counter)
