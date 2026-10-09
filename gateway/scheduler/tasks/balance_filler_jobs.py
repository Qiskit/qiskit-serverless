"""Keep a minimum number of jobs running on a scarce Fleets compute profile."""

import logging

from django.core.exceptions import ValidationError

from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from core.config_key import ConfigKey
from core.domain import compute_profile as compute_profile_domain
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from core.models import Config, Job, Program
from core.domain.exceptions.invalid_job_transition_exception import InvalidJobTransitionException
from core.services.job_transitions import JobTransitionService
from core.services.runners import RunnerError, RunnerRetryableError
from core.services.storage import get_arguments_storage
from scheduler.health import DB_EXCEPTIONS
from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.schedule import FleetsJobCanceller, FleetsJobSubmitter, log_cancel_failure
from .task import SchedulerTask

logger = logging.getLogger("scheduler.BalanceFillerJobs")

# Loops to skip after a failed creation to avoid create a failed job per second if CE is down.
RETRY_AFTER_LOOPS = 60


class BalanceFillerJobs(SchedulerTask):
    """Keep real plus filler jobs on one compute profile at the configured minimum.

    - The compute profile is derived from the filler program's default size.

    - A filler job belongs to the feature only while it matches the program.id and that profile
    Changing the filler function or the compute profile will stop all the previous job filler

    - Filler jobs are submitted directly instead of through the queue
    ScheduleFleetsJobs feeds, which would put them in competition with real queued jobs.
    """

    def __init__(
        self,
        kill_signal: KillSignal,
        metrics: SchedulerMetrics,
        transitions: JobTransitionService | None = None,
        submitter: FleetsJobSubmitter | None = None,
        canceller: FleetsJobCanceller | None = None,
    ):
        self.kill_signal = kill_signal
        self.metrics = metrics
        self.transitions = transitions or JobTransitionService()
        self.submitter = submitter or FleetsJobSubmitter(self.transitions)
        self.canceller = canceller or FleetsJobCanceller(self.transitions)
        self._retry_loops = 0

    def run(self):
        """Stop every filler job when the feature is off, otherwise balance them."""
        self._discard_unsubmitted_filler_jobs()

        program = self._get_filler_program()
        filler_jobs = list(
            Job.objects.filter(filler=True, runner=Program.FLEETS, status__in=Job.RUNNING_STATUSES).order_by("created")
        )

        if program is None:
            self._drain_filler_jobs(filler_jobs)
        else:
            self._balance_filler_jobs(program, filler_jobs)

    def _drain_filler_jobs(self, filler_jobs: list[Job]) -> None:
        """Stop every filler job, because the feature is off or misconfigured."""
        # Cleared rather than zeroed: nothing is measuring that profile now.
        self.metrics.set_filler_profile_slots(0)
        self.metrics.clear_filler_profile_jobs()
        if filler_jobs:
            logger.info("[BalanceFillerJobs] stopping %s filler job(s), the feature is off", len(filler_jobs))
        self._stop_filler_jobs(filler_jobs)

    def _balance_filler_jobs(self, program: Program, filler_jobs: list[Job]) -> None:
        """Stop the filler jobs that no longer belong, then close the gap to the target."""
        profile_row = program.default_size.compute_profile
        # Log label only: primary keys are free text, so a row may carry the instance-family prefix.
        profile_label = compute_profile_domain.normalize(profile_row.compute_profile_id)
        slots = Config.get_int(ConfigKey.FILLER_SLOTS)
        real_running = Job.objects.filter(
            compute_profile_fk=profile_row,
            runner=Program.FLEETS,
            status__in=Job.RUNNING_STATUSES,
            filler=False,
        ).count()
        target = max(0, slots - real_running)
        logger.info(
            "[BalanceFillerJobs] profile=%s slots=%s real_running=%s target=%s",
            profile_label,
            slots,
            real_running,
            target,
        )
        self.metrics.set_filler_profile_slots(slots)
        self.metrics.set_filler_profile_jobs(real_running, "real")

        # Compared on compute_profile_fk, not on the normalized string: two
        # ComputeProfile rows can normalize to the same string, and jobs on a profile
        # the balancer no longer protects would then never be stopped.
        expected = (program.pk, profile_row.pk)
        stale = [job for job in filler_jobs if (job.program_id, job.compute_profile_fk_id) != expected]
        current = [job for job in filler_jobs if (job.program_id, job.compute_profile_fk_id) == expected]
        self.metrics.set_filler_profile_jobs(len(current), "filler")

        if stale:
            logger.info(
                "[BalanceFillerJobs] stopping %s filler job(s) on another program or compute profile", len(stale)
            )
            self._stop_filler_jobs(stale)

        if len(current) < target:
            self._create_filler_job(program)
        elif len(current) > target:
            # Draining rows count toward the target but cannot be shed again, so take the stops from the rest
            stoppable = [job for job in current if job.status != Job.STOPPING]
            self._stop_filler_jobs(stoppable[: max(0, len(stoppable) - target)])

    def _get_filler_program(self) -> Program | None:  # pylint: disable=too-many-return-statements
        """Return the configured filler program, or None when the feature is off.

        Every reason to return None is handled the same way by the caller: no new filler
        job, and the running ones are stopped.
        """
        if Config.get_bool(ConfigKey.MAINTENANCE):
            self._log_deactivated("maintenance mode is on")
            return None

        if not Config.get_bool(ConfigKey.FILLER_ENABLED):
            self._log_deactivated(f"{ConfigKey.FILLER_ENABLED.value} is false")
            return None

        slots = Config.get_int(ConfigKey.FILLER_SLOTS)
        if slots <= 0:
            self._log_deactivated(f"{ConfigKey.FILLER_SLOTS.value} is {slots}")
            return None

        program = self._lookup_filler_function()
        if program is None:
            return None

        if program.runner != Program.FLEETS:
            # get_arguments_storage dispatches on runner, so a Ray program would put
            # the arguments where the Fleets submit cannot find them.
            self._log_deactivated(f"function {program} runner is {program.runner}, expected {Program.FLEETS}")
            return None

        if program.disabled:
            self._log_deactivated(f"function {program} is disabled")
            return None

        # These three mirror what FleetsRunner and the arguments storage raise on, so
        # the feature deactivates instead of creating a FAILED job every loop.
        project = program.code_engine_project
        if project is None:
            self._log_deactivated(f"function {program} has no Code Engine project")
            return None

        if not project.active:
            self._log_deactivated(f"Code Engine project {project.project_name} is not active")
            return None

        if not project.cos_bucket_user_data_name:
            self._log_deactivated(f"Code Engine project {project.project_name} has no user data COS bucket")
            return None

        if program.default_size is None:
            self._log_deactivated(f"function {program} has no default size")
            return None

        return program

    def _lookup_filler_function(self) -> Program | None:
        """Return the Program the config key names, or None after saying why it cannot.

        With a slash the value is ``provider/title``, without one it is the Program's id.
        The name form needs a provider function, which anyone with write access to the
        provider can update, while an id can name a personal function that only its
        author can update, leaving the feature dependent on one person's key.
        """
        value = Config.get(ConfigKey.FILLER_FUNCTION).strip()
        if not value:
            self._log_deactivated(f"{ConfigKey.FILLER_FUNCTION.value} is empty")
            return None

        programs = Program.objects.select_related("author", "default_size__compute_profile", "code_engine_project")
        try:
            if "/" in value:
                parts = value.split("/")
                if len(parts) != 2 or not all(parts):
                    self._log_deactivated(
                        f"{ConfigKey.FILLER_FUNCTION.value} is {value!r}, expected provider/title or an id"
                    )
                    return None
                return programs.get(provider__name=parts[0], title=parts[1])
            return programs.get(id=value)
        except Program.DoesNotExist:
            self._log_deactivated(f"function {value} does not exist")
            return None
        except ValidationError:
            self._log_deactivated(f"{ConfigKey.FILLER_FUNCTION.value} is {value!r}, which is not a valid uuid")
            return None

    def _log_deactivated(self, reason: str) -> None:
        """Log why the feature is not active."""
        logger.info("[BalanceFillerJobs] deactivated: %s", reason)

    def _discard_unsubmitted_filler_jobs(self) -> None:
        """Fail filler jobs stuck in QUEUED with no fleet.

        Creation submits in the same call that saves the row, so QUEUED means something
        failed in between. Nothing else ever looks at such a row again: the status
        updates only cover RUNNING_STATUSES, so not even the 24h timeout reaches it.
        """
        stuck = Job.objects.filter(filler=True, status=Job.QUEUED, fleet_id__isnull=True)
        for job in stuck:
            logger.error(
                "[BalanceFillerJobs] job_id=%s filler job was never submitted, discarding it; "
                "check Code Engine for an orphan fleet",
                job.id,
            )
            self._mark_failed(job)

    def _create_filler_job(self, program: Program) -> None:
        """Create and submit one filler job, the most this task creates per loop.

        One per loop rather than the whole shortfall, so the COS upload and the Code
        Engine submit each one costs stay off the critical path of this shared loop.
        """
        if self._retry_loops > 0:
            self._retry_loops -= 1
            return
        # a shutdown or a paused region buys no delay
        if self.kill_signal.received or self.submitter.paused(program.code_engine_project.region):
            return
        try:
            if not self._submit_filler_job(program):
                self._retry_loops = RETRY_AFTER_LOOPS
        except RunnerRetryableError:
            # no fleet was created, and the region's breaker decides when to try again
            pass

    def _submit_filler_job(self, program: Program) -> bool:
        """Create and submit one filler job. True when it reached PENDING. Raises when its region is unavailable."""
        project = program.code_engine_project
        job = Job(
            program=program,
            # Filler jobs are excluded from billing, metrics and the fair-share tally
            # by Job.filler, so they need no service user of their own.
            author=program.author,
            filler=True,
            runner=Program.FLEETS,
            compute_profile_fk=program.default_size.compute_profile,
            size_source=Job.SIZE_SOURCE_NONE,
            function_size=program.default_size,
            status=Job.QUEUED,
            env_vars="{}",
            ce_project_name=project.project_name,
            ce_region=project.region,
        )
        # Two except blocks because a failure before job.save() leaves no row, and one
        # after it leaves a row nothing else can reach.
        try:
            # Arguments first: a COS failure then leaves no orphan row behind.
            get_arguments_storage(job).save("{}")
            job.save()
        except DB_EXCEPTIONS:
            # Never swallowed: main.py counts consecutive database failures to restart
            # the pod, and returning normally here would clear a streak.
            raise
        except Exception as ex:  # pylint: disable=broad-exception-caught
            self._log_creation_failed(ex)
            return False

        try:
            job = self.submitter.submit(
                job,
                TraceContextTextMapPropagator().extract(carrier={}),
                context=JobEventContext.FILLER_SUBMIT,
            )
        except DB_EXCEPTIONS:
            raise
        except RunnerRetryableError as ex:
            self._mark_failed(job)
            self._log_creation_failed(ex)
            raise
        except Exception as ex:  # pylint: disable=broad-exception-caught
            if job.status == Job.QUEUED and not job.fleet_id:
                # It raised before any write, so no fleet exists and this row is
                # already unreachable. _discard_unsubmitted_filler_jobs is the net for
                # the cases no except block sees.
                self._mark_failed(job)
            self._log_creation_failed(ex)
            return False

        submitted = job.status == Job.PENDING
        self.metrics.increment_filler_jobs_created("submitted" if submitted else "failed")
        logger.info("[BalanceFillerJobs] job_id=%s filler job submitted with status=%s", job.id, job.status)
        # Not reaching PENDING means submit() swallowed a RunnerError.
        return submitted

    def _log_creation_failed(self, ex: Exception) -> None:
        """Report a failed creation.

        Caught here rather than by the scheduler's generic handler, which would log a
        traceback once a second. RETRY_AFTER_LOOPS, or the region's breaker, limits how often it happens.
        """
        logger.error("[BalanceFillerJobs] could not create filler job: %s", str(ex))
        self.metrics.increment_filler_jobs_created("failed")

    def _stop_filler_jobs(self, jobs: list[Job]) -> None:
        """Ask for a stop on the given filler jobs."""
        for job in jobs:
            if self.kill_signal.received:
                return
            if job.status == Job.STOPPING:
                # Already draining: no second cancel to send.
                continue
            self._stop_one_filler_job(job)

    def _stop_one_filler_job(self, job: Job) -> None:
        """Cancel the fleet and write STOPPING, or STOPPED when there was nothing to cancel."""
        if self.canceller.paused(job.ce_region):
            return
        try:
            if self.canceller.cancel(job, context=JobEventContext.FILLER_STOP):
                # STOPPING: the status poller counts it when it writes the terminal status.
                logger.info("[BalanceFillerJobs] job_id=%s filler job cancel sent", job.id)
                return
            self.transitions.to_stopped(job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.FILLER_STOP)
        except RunnerError as ex:
            # Left active: a status change here would claim a cancel that never left.
            log_cancel_failure(logger, job, ex, prefix="[BalanceFillerJobs] ")
            return
        except InvalidJobTransitionException:
            logger.info("job_id=%s transition rejected, skipping the stop", job.id)
            return

        # Terminal already, so the poller never sees this row and this is the only place to count it.
        self.metrics.increment_filler_jobs_stopped()
        logger.info("[BalanceFillerJobs] job_id=%s filler job stopped, nothing to cancel", job.id)

    def _mark_failed(self, job: Job) -> None:
        """Write FAILED on a job whose submit never happened.

        Not the stopped counter: nothing stopped it, its creation broke, and that counter is
        cross-checked against the FILLER_STOP events.
        """
        try:
            self.transitions.to_failed(job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.FILLER_FAILED)
        except InvalidJobTransitionException:
            # Lost the race: something else already moved this job to a terminal status.
            logger.info("job_id=%s already in a terminal status, skipping FAILED", job.id)
