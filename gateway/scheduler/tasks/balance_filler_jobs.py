"""Keep a minimum number of jobs running on a scarce Fleets compute profile."""

import logging

from django.core.exceptions import ValidationError

from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from core.config_key import ConfigKey
from core.domain import compute_profile as compute_profile_domain
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from core.models import Config, Job, JobEvent, Program
from core.services.runners import get_runner, RunnerError
from core.services.storage import get_arguments_storage
from scheduler.health import DB_EXCEPTIONS
from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.schedule import execute_fleets_job
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

    def __init__(self, kill_signal: KillSignal, metrics: SchedulerMetrics):
        self.kill_signal = kill_signal
        self.metrics = metrics
        self._retry_loops = 0

    def run(self):
        """Stop every filler job when the feature is off, otherwise balance them."""
        self._discard_unsubmitted_filler_jobs()

        program = self._get_filler_program()
        filler_jobs = list(Job.objects.filter(filler=True, status__in=Job.RUNNING_STATUSES).order_by("created"))

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
        # Primary keys are free text, so a row may carry the instance-family prefix.
        compute_profile = compute_profile_domain.normalize(profile_row.compute_profile_id)
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
            compute_profile,
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
            self._create_filler_job(program, compute_profile)
        elif len(current) > target:
            self._stop_filler_jobs(current[: len(current) - target])

    def _get_filler_program(self) -> Program | None:  # pylint: disable=too-many-return-statements
        """Return the configured filler program, or None when the feature is off.

        Every reason to return None is handled the same way by the caller: no new filler
        job, and the running ones are stopped.
        """
        if Config.get_bool(ConfigKey.MAINTENANCE):
            return self._deactivated("maintenance mode is on")

        if not Config.get_bool(ConfigKey.FILLER_ENABLED):
            return self._deactivated(f"{ConfigKey.FILLER_ENABLED.value} is false")

        slots = Config.get_int(ConfigKey.FILLER_SLOTS)
        if slots <= 0:
            return self._deactivated(f"{ConfigKey.FILLER_SLOTS.value} is {slots}")

        program = self._lookup_filler_function()
        if program is None:
            return None

        if program.runner != Program.FLEETS:
            # get_arguments_storage dispatches on runner, so a Ray program would put
            # the arguments where the Fleets submit cannot find them.
            return self._deactivated(f"function {program} runner is {program.runner}, expected {Program.FLEETS}")

        if program.disabled:
            return self._deactivated(f"function {program} is disabled")

        # These three mirror what FleetsRunner and the arguments storage raise on, so
        # the feature deactivates instead of creating a FAILED job every loop.
        project = program.code_engine_project
        if project is None:
            return self._deactivated(f"function {program} has no Code Engine project")

        if not project.active:
            return self._deactivated(f"Code Engine project {project.project_name} is not active")

        if not project.cos_bucket_user_data_name:
            return self._deactivated(f"Code Engine project {project.project_name} has no user data COS bucket")

        if program.default_size is None:
            return self._deactivated(f"function {program} has no default size")

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
            return self._deactivated(f"{ConfigKey.FILLER_FUNCTION.value} is empty")

        programs = Program.objects.select_related("author", "default_size__compute_profile", "code_engine_project")
        try:
            if "/" in value:
                parts = value.split("/")
                if len(parts) != 2 or not all(parts):
                    return self._deactivated(
                        f"{ConfigKey.FILLER_FUNCTION.value} is {value!r}, expected provider/title or an id"
                    )
                return programs.get(provider__name=parts[0], title=parts[1])
            return programs.get(id=value)
        except Program.DoesNotExist:
            return self._deactivated(f"function {value} does not exist")
        except ValidationError:
            return self._deactivated(f"{ConfigKey.FILLER_FUNCTION.value} is {value!r}, which is not a valid uuid")

    def _deactivated(self, reason: str) -> None:
        """Log why the feature is not active and return None implicitly.

        Do not add an explicit `return None`: pylint rejects it (R1711).
        """
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

    def _create_filler_job(self, program: Program, compute_profile: str) -> None:
        """Create and submit one filler job, the most this task creates per loop.

        One per loop rather than the whole shortfall, so the COS upload and the Code
        Engine submit each one costs stay off the critical path of this shared loop.
        """
        if self._retry_loops > 0:
            self._retry_loops -= 1
            return
        # A shutdown is not a failure of the work, so it buys no delay.
        if self.kill_signal.received:
            return
        if not self._submit_filler_job(program, compute_profile):
            self._retry_loops = RETRY_AFTER_LOOPS

    def _submit_filler_job(self, program: Program, compute_profile: str) -> bool:
        """Create and submit one filler job. True when it reached PENDING."""
        project = program.code_engine_project
        job = Job(
            program=program,
            # Filler jobs are excluded from billing, metrics and the fair-share tally
            # by Job.filler, so they need no service user of their own.
            author=program.author,
            filler=True,
            runner=Program.FLEETS,
            compute_profile=compute_profile,
            compute_profile_fk=program.default_size.compute_profile,
            # Nobody asked for a size, so the attribution does not apply.
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
            return self._creation_failed(ex)

        try:
            job = execute_fleets_job(
                job,
                TraceContextTextMapPropagator().extract(carrier={}),
                context=JobEventContext.FILLER_SUBMIT,
            )
        except DB_EXCEPTIONS:
            raise
        except Exception as ex:  # pylint: disable=broad-exception-caught
            if job.status == Job.QUEUED and not job.fleet_id:
                # It raised before runner.submit(), so no fleet exists and this row is
                # already unreachable. _discard_unsubmitted_filler_jobs is the net for
                # the cases no except block sees.
                self._mark_failed(job)
            return self._creation_failed(ex)

        submitted = job.status == Job.PENDING
        self.metrics.increment_filler_jobs_created("submitted" if submitted else "failed")
        logger.info("[BalanceFillerJobs] job_id=%s filler job submitted with status=%s", job.id, job.status)
        # Not reaching PENDING means execute_fleets_job swallowed a RunnerError.
        return submitted

    def _creation_failed(self, ex: Exception) -> bool:
        """Report a failed creation and give the caller the value to return.

        Caught here rather than by the scheduler's generic handler, which would log a
        traceback once a second. RETRY_AFTER_LOOPS already limits this to one a minute.
        """
        logger.error("[BalanceFillerJobs] could not create filler job: %s", str(ex))
        self.metrics.increment_filler_jobs_created("failed")
        return False

    def _stop_filler_jobs(self, jobs: list[Job]) -> None:
        """Stop the given filler jobs, cancelling the fleet before writing STOPPED."""
        for job in jobs:
            if self.kill_signal.received:
                return
            self._stop_one_filler_job(job)

    def _stop_one_filler_job(self, job: Job) -> None:
        """Cancel this job's fleet if it has one, then write STOPPED on the row."""
        if job.fleet_id:
            try:
                get_runner(job).stop()
            except RunnerError as ex:
                # Left active on purpose: writing STOPPED would hide a fleet still
                # holding the node, and the balancer would create another on top.
                logger.error("[BalanceFillerJobs] job_id=%s error stopping filler job: %s", job.id, str(ex))
                return

        self._mark_stopped(job)
        logger.info("[BalanceFillerJobs] job_id=%s filler job stopped", job.id)

    def _mark_failed(self, job: Job) -> None:
        """Write FAILED on a job whose submit never happened.

        Not _mark_stopped: nothing stopped it, its creation broke, and that counter is
        cross-checked against the FILLER_STOP events.
        """
        job.update_fields({"status": Job.FAILED, "sub_status": None})
        JobEvent.objects.add_status_event(
            job_id=job.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.FILLER_FAILED,
            status=Job.FAILED,
        )

    def _mark_stopped(self, job: Job) -> None:
        """Write STOPPED on the job, record the event, and count it."""
        job.update_fields({"status": Job.STOPPED, "sub_status": None})
        JobEvent.objects.add_status_event(
            job_id=job.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.FILLER_STOP,
            status=Job.STOPPED,
        )
        self.metrics.increment_filler_jobs_stopped()
