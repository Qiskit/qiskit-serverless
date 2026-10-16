"""Stop the Fleets jobs Code Engine is handling for a blocked account, plan and subscription."""

import logging

from core.config_key import ConfigKey
from core.domain.exceptions.invalid_job_transition_exception import InvalidJobTransitionException
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from core.models import BlockedCloudResource, Config, Job, Program
from core.services.runners import RunnerError, RunnerRetryableError

from scheduler.kill_signal import KillSignal
from scheduler.schedule import FleetsJobCanceller, first_cancel_refusal
from .task import SchedulerTask

logger = logging.getLogger("scheduler.StopBlockedFleetsJobs")

_CONTEXT = JobEventContext.BLOCKED_RESOURCE_STOP


class StopBlockedFleetsJobs(SchedulerTask):
    """Cancel the PENDING and RUNNING Fleets jobs of a blocked resource. A QUEUED one is held back at submit."""

    def __init__(self, kill_signal: KillSignal, canceller: FleetsJobCanceller):
        self.kill_signal = kill_signal
        self.canceller = canceller

    def run(self) -> None:
        """Ask once per tick for every blocked job: a cancel that does not land is asked again next tick."""
        if not Config.get_bool(ConfigKey.BLOCKED_JOBS_STOP_ENABLED) or not BlockedCloudResource.objects.exists():
            return

        jobs = Job.objects.filter(runner=Program.FLEETS, filler=False, status__in=[Job.PENDING, Job.RUNNING])
        for job in jobs:
            if self.kill_signal.received:
                return
            if BlockedCloudResource.blocks(job.account_id, job.plan_id, job.subscription_id):
                self._stop(job)

    def _stop(self, job: Job) -> None:
        if self.canceller.paused(job.ce_region):
            return

        logger.warning(
            "job_id=%s account_id=%s plan_id=%s subscription_id=%s resource is blocked: stopping the job.",
            job.id,
            job.account_id,
            job.plan_id,
            job.subscription_id,
        )
        try:
            if not self.canceller.cancel(job, context=_CONTEXT):
                self.canceller.transitions.to_stopped(job, origin=JobEventOrigin.SCHEDULER, context=_CONTEXT)
        except RunnerRetryableError as ex:
            logger.warning("job_id=%s fleet_id=%s cancel not delivered: %s", job.id, job.fleet_id, str(ex))
        except RunnerError as ex:
            log = logger.error if first_cancel_refusal(job) else logger.debug
            log("job_id=%s fleet_id=%s cancel could not be sent: %s", job.id, job.fleet_id, str(ex))
        except InvalidJobTransitionException as ex:
            logger.info("job_id=%s transition rejected, skipping: %s", job.id, str(ex))
