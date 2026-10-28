"""Stop the Fleets jobs Code Engine is handling for a blocked account, plan and subscription."""

import logging

from core.config_key import ConfigKey
from core.domain.exceptions.invalid_job_transition_exception import InvalidJobTransitionException
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from core.models import BlockedCloudResource, Config, Job, JobEvent, Program
from core.services.runners import RunnerError, RunnerRetryableError

from scheduler.kill_signal import KillSignal
from scheduler.schedule import FleetsJobCanceller, first_cancel_refusal
from .task import SchedulerTask

logger = logging.getLogger("scheduler.StopBlockedFleetsJobs")

_CONTEXT = JobEventContext.BLOCKED_RESOURCE_STOP
# The client reads this code to explain a cancelled job's missing result, so it must not change
BLOCKED_RESOURCE_ERROR_CODE = "BLOCKED_RESOURCE"
BLOCKED_RESOURCE_ERROR_MESSAGE = (
    "This job was cancelled because your account, plan or subscription is blocked, "
    "so its result may be missing or incomplete. Run it again once the block is lifted."
)


class StopBlockedFleetsJobs(SchedulerTask):
    """Cancel the PENDING and RUNNING Fleets jobs of a blocked resource. A QUEUED one is held back at submit."""

    def __init__(self, kill_signal: KillSignal, canceller: FleetsJobCanceller):
        self.kill_signal = kill_signal
        self.canceller = canceller

    def run(self) -> None:
        """Ask once per tick for every blocked job: a cancel that does not land is asked again next tick.

        The blocked rows are read once per pass, so a change to them applies from the next tick.
        """
        if not Config.get_bool(ConfigKey.BLOCKED_JOBS_STOP_ENABLED):
            return
        blocked = BlockedCloudResource.blocked_jobs_filter()
        if blocked is None:
            return

        # Join what a stop reads: program and project (runner), provider (billing), author (Runtime API mirror).
        jobs = Job.objects.filter(
            blocked, runner=Program.FLEETS, filler=False, status__in=[Job.PENDING, Job.RUNNING]
        ).select_related("author", "program__provider", "program__code_engine_project")
        for job in jobs:
            if self.kill_signal.received:
                return
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
            JobEvent.objects.add_error_event(
                job_id=job.id,
                origin=JobEventOrigin.SCHEDULER,
                context=_CONTEXT,
                code=BLOCKED_RESOURCE_ERROR_CODE,
                message=BLOCKED_RESOURCE_ERROR_MESSAGE,
                exception="BlockedResource",
                args={"account_id": job.account_id, "plan_id": job.plan_id, "subscription_id": job.subscription_id},
            )
        except RunnerRetryableError as ex:
            logger.warning("job_id=%s fleet_id=%s cancel not delivered: %s", job.id, job.fleet_id, str(ex))
        except RunnerError as ex:
            log = logger.error if first_cancel_refusal(job) else logger.debug
            log("job_id=%s fleet_id=%s cancel could not be sent: %s", job.id, job.fleet_id, str(ex))
        except InvalidJobTransitionException as ex:
            logger.info("job_id=%s transition rejected, skipping: %s", job.id, str(ex))
