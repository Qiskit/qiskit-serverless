"""Update Fleets jobs statuses service."""

import logging
from datetime import datetime, timezone

from concurrency.exceptions import RecordModifiedError
from django.conf import settings

from core.models import Job, JobEvent, Program
from core.services.runners import get_runner, RunnerError
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

    # pylint: disable=too-many-branches
    def update_job_status(self, job: Job):
        """Update status of one Fleets job."""
        if not job.fleet_id:
            logger.warning(
                "job_id=%s Fleets job doesn't have fleet_id. Return false",
                job.id,
            )
            return False

        runner = get_runner(job)

        try:
            job_new_status = runner.status()
        except RunnerError as ex:
            job.status = Job.FAILED
            job.sub_status = None
            job.env_vars = "{}"
            try:
                job.save()
                JobEvent.objects.add_status_event(
                    job_id=job.id,
                    origin=JobEventOrigin.SCHEDULER,
                    context=JobEventContext.UPDATE_JOB_STATUS,
                    status=job.status,
                )
                self._increment_terminal_counter(job)
                logger.warning(
                    "job_id=%s error=%s Error getting status, set job as FAILED",
                    job.id,
                    str(ex),
                )
            except RecordModifiedError:
                logger.warning(
                    "job_id=%s error=%s Error getting status + RecordModifiedError setting job as FAILED",
                    job.id,
                    str(ex),
                )
            return True

        status_has_changed = False

        if job_new_status != job.status:
            logger.info(
                "job_id=%s user_id=%s Changing status from %s to %s",
                job.id,
                job.author.id,
                job.status,
                job_new_status,
            )
            status_has_changed = True
            job.status = job_new_status

            if job.in_terminal_state():
                job.sub_status = None
                job.env_vars = "{}"
                # Retrieve results from COS and save to database
                try:
                    result_str = runner.get_result_from_cos()
                    if result_str:
                        job.result = result_str
                        logger.info("Retrieved and saved results for Fleets job [%s]", job.id)
                except Exception as ex:  # pylint: disable=broad-exception-caught
                    logger.warning("Failed to retrieve results for Fleets job [%s]: %s", job.id, str(ex))
                job.logs = ""
                if job.status == Job.SUCCEEDED:
                    self._record_execution_duration(job)

        try:
            job.save()

            if status_has_changed:
                JobEvent.objects.add_status_event(
                    job_id=job.id,
                    origin=JobEventOrigin.SCHEDULER,
                    context=JobEventContext.UPDATE_JOB_STATUS,
                    status=job.status,
                )
                if job.in_terminal_state():
                    self._increment_terminal_counter(job)
        except RecordModifiedError:
            status_has_changed = False
            logger.warning("job_id=%s RecordModifiedError on save", job.id)

        return status_has_changed

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

        fleets_counter = 0
        # Note: with LIMITS_MAX_FLEETS potentially reaching 1000+ concurrent jobs, updating statuses
        # sequentially will become a bottleneck. This loop should be parallelized using multiple
        # threads or batched processing for performance reasons.
        jobs = Job.objects.filter(status__in=Job.RUNNING_STATUSES, runner=Program.FLEETS)
        for job in jobs:
            if self.kill_signal.received:
                return
            if self.update_job_status(job):
                fleets_counter += 1

        if fleets_counter:
            logger.info("Updated %s Fleets jobs.", fleets_counter)
