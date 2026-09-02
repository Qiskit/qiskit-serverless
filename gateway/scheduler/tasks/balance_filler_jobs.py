"""Keep a minimum number of jobs running on a scarce Fleets compute profile."""

import logging
from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.contrib.auth import get_user_model
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

User = get_user_model()

# Loops to skip after a failure before trying the same thing again, which turns
# tens of thousands of doomed retries a day into about 1,400. It counts loops, not
# seconds: the countdown only advances on loops that reach the same code path, so a
# creation delay pauses while real jobs fill the slots.
RETRY_AFTER_LOOPS = 60

# Churn breaker. A filler job that ends on its own (FAILED because the submit was
# rejected, or SUCCEEDED because the program exited) is replaced a second later,
# forever, with nothing counting it. STOPPED is excluded: that is the balancer
# making room for real work, or the 24h timeout, and both are the feature working.
# Three, not five: the create path backs off for RETRY_AFTER_LOOPS after each
# failure, so a steadily-failing filler program only produces about four deaths
# per window and a limit of five would sit right on that boundary.
CHURN_WINDOW = timedelta(minutes=5)
CHURN_LIMIT = 3


class BalanceFillerJobs(SchedulerTask):
    """Keep real plus filler jobs on one compute profile at the configured minimum.

    The compute profile is not configured directly: it is derived from the filler
    program's default size, so it cannot drift away from the program it belongs to.
    A filler job belongs to the feature only while it matches both, the configured
    program and that program's profile, so re-pointing either one drains the jobs
    left behind.

    Filler jobs skip the queue that ScheduleFleetsJobs feeds. Going through it would
    put them in competition with real queued jobs for the free Fleets slots, and
    would leave the balancer unable to say when the capacity it protects is held.
    """

    def __init__(self, kill_signal: KillSignal, metrics: SchedulerMetrics):
        self.kill_signal = kill_signal
        self.metrics = metrics
        self._last_logged: dict[str, tuple] = {}
        self._retry_after: dict[str, int] = {}

    def run(self):
        """Stop every filler job when the feature is off, otherwise balance them."""
        self._discard_unsubmitted_filler_jobs()

        program = self._get_filler_program()
        filler_jobs = list(Job.objects.filter(filler=True, status__in=Job.RUNNING_STATUSES).order_by("created"))

        if program is None:
            self._drain_filler_jobs(filler_jobs)
        else:
            self._balance_filler_jobs(program, filler_jobs)

        self._forget_finished_jobs(filler_jobs)

    def _drain_filler_jobs(self, filler_jobs: list[Job]) -> None:
        """Stop every filler job, because the feature is off or misconfigured.

        _get_filler_program has already said which of the two at INFO, so this only
        reports the cleanup that follows from it.
        """
        self._clear_throttle("status")
        self._clear_throttle("stale")
        if not filler_jobs:
            self._clear_throttle("drain")
            return
        self._log_throttled(
            "drain",
            logging.INFO,
            "[BalanceFillerJobs] stopping %s filler job(s), the feature is off",
            len(filler_jobs),
        )
        self._stop_filler_jobs(filler_jobs)

    def _balance_filler_jobs(self, program: Program, filler_jobs: list[Job]) -> None:
        """Stop the filler jobs that no longer belong, then close the gap to the target."""
        self._clear_throttle("deactivated")
        self._clear_throttle("drain")

        profile_row = program.default_size.compute_profile
        compute_profile = self._compute_profile_of(program)
        slots = Config.get_int(ConfigKey.FILLER_SLOTS)
        real_running = Job.objects.filter(
            compute_profile_fk=profile_row,
            runner=Program.FLEETS,
            status__in=Job.RUNNING_STATUSES,
            filler=False,
        ).count()
        target = max(0, slots - real_running)
        self._log_throttled(
            "status",
            logging.INFO,
            "[BalanceFillerJobs] profile=%s slots=%s real_running=%s target=%s",
            compute_profile,
            slots,
            real_running,
            target,
        )

        # A filler job belongs to the feature only while it matches both halves: the
        # configured program and the profile derived from it. Another profile holds
        # capacity nobody asked it to hold, and another program holds the right
        # capacity with the code the operator replaced, so both are stopped.
        # The profile half is compared on compute_profile_fk, the same key the
        # occupancy count uses: two ComputeProfile rows can normalize to the same
        # string, so comparing strings here would leave jobs sitting on a profile the
        # balancer no longer protects, with nothing to stop them.
        expected = (program.pk, profile_row.pk)
        stale = [job for job in filler_jobs if (job.program_id, job.compute_profile_fk_id) != expected]
        current = [job for job in filler_jobs if (job.program_id, job.compute_profile_fk_id) == expected]

        if stale:
            self._log_throttled(
                "stale",
                logging.INFO,
                "[BalanceFillerJobs] stopping %s filler job(s) on another program or compute profile",
                len(stale),
            )
            self._stop_filler_jobs(stale)
        else:
            self._clear_throttle("stale")

        if len(current) < target:
            self._create_filler_job(program, compute_profile)
        elif len(current) > target:
            self._stop_filler_jobs(current[: len(current) - target])

    def _log_throttled(self, key: str, level: int, message: str, *args) -> None:
        """Log at `level` when this key's arguments change, at DEBUG when they repeat.

        The scheduler loop runs about once a second, so any unconditional log line
        in this task becomes tens of thousands of identical entries a day. Every
        repeating line here goes through this method for that reason.
        """
        if self._last_logged.get(key) != args:
            logger.log(level, message, *args)
            self._last_logged[key] = args
        else:
            logger.debug(message, *args)

    def _clear_throttle(self, key: str) -> None:
        """Forget a key's last arguments so its next occurrence logs at its own level.

        Throttling is meant to silence repeats, not recurrences: without this, a
        condition that clears and comes back would never be reported again for the
        life of the scheduler process.
        """
        self._last_logged.pop(key, None)

    def _wait_before_retry(self, key: str) -> bool:
        """Return True while `key` is still serving out its retry delay."""
        remaining = self._retry_after.get(key, 0)
        if remaining <= 0:
            return False
        self._retry_after[key] = remaining - 1
        return True

    def _forget_finished_jobs(self, filler_jobs: list[Job]) -> None:
        """Drop retry state for jobs that are no longer active, so it cannot grow."""
        live = {f"stop:{job.id}" for job in filler_jobs}
        for key in [k for k in self._retry_after if k.startswith("stop:") and k not in live]:
            del self._retry_after[key]
            self._last_logged.pop(key, None)

    def _compute_profile_of(self, program: Program) -> str:
        """Return the program's default compute profile in canonical form.

        ComputeProfile primary keys are free text with no validation anywhere, so a
        row can carry the prefixed form. This value is what the filler jobs store in
        Job.compute_profile and what the next loop matches them by, so normalizing
        keeps it stable. Occupancy is counted on compute_profile_fk instead, because
        a job sized through the t-shirt size paths stores the primary key verbatim
        rather than the canonical form.
        """
        # normalize() is typed Optional[str] because it maps None and "" to None,
        # but compute_profile_id is a non-empty primary key, so this is always a str.
        return compute_profile_domain.normalize(program.default_size.compute_profile.compute_profile_id)

    def _is_churning(self) -> bool:
        """Return True when filler jobs have been dying on their own.

        This counts the terminal JobEvent, not the Job row. Counting rows by
        Job.created only catches deaths faster than CHURN_WINDOW: a fleet that
        fails six minutes after it was created is already outside the window by
        the time it reaches FAILED, so the breaker would never fire for it.
        JobEvent.created is auto_now_add and records when the death happened.
        (Job.updated cannot be used for this: update_fields and save_direct issue
        a raw UPDATE that skips auto_now.)
        """
        recent_deaths = (
            JobEvent.objects.filter(
                job__filler=True,
                data__status__in=[Job.FAILED, Job.SUCCEEDED],
                created__gte=datetime.now(timezone.utc) - CHURN_WINDOW,
            )
            .values("job_id")
            .distinct()
            .count()
        )
        if recent_deaths < CHURN_LIMIT:
            self._clear_throttle("churn")
            return False
        self._log_throttled(
            "churn",
            logging.ERROR,
            "[BalanceFillerJobs] %s filler jobs ended on their own in the last %s; "
            "not creating more until that stops",
            recent_deaths,
            CHURN_WINDOW,
        )
        return True

    def _get_filler_program(self) -> Program | None:  # pylint: disable=too-many-return-statements
        """Return the configured filler program, or None when the feature is off.

        Every reason to return None is treated the same way by the caller: no new
        filler job, and the running ones are stopped. Switched off on purpose and
        misconfigured are the same operational decision, not a system error.
        """
        if Config.get_bool(ConfigKey.MAINTENANCE):
            return self._deactivated("maintenance mode is on")

        if not Config.get_bool(ConfigKey.FILLER_ENABLED):
            return self._deactivated(f"{ConfigKey.FILLER_ENABLED.value} is false")

        # Zero slots means the same as switched off, and it is how the feature is
        # drained: the caller stops every filler job when this returns None. Read
        # again in run(), off the same DYNAMIC_CONFIG_CACHE_TTL cache.
        slots = Config.get_int(ConfigKey.FILLER_SLOTS)
        if slots <= 0:
            return self._deactivated(f"{ConfigKey.FILLER_SLOTS.value} is {slots}")

        program_id = Config.get(ConfigKey.FILLER_PROGRAM_ID).strip()
        if not program_id:
            return self._deactivated(f"{ConfigKey.FILLER_PROGRAM_ID.value} is empty")

        try:
            program = Program.objects.select_related("default_size__compute_profile", "code_engine_project").get(
                id=program_id
            )
        except (Program.DoesNotExist, ValidationError, ValueError):
            # Program.id is a UUIDField, so a value that is not a UUID raises
            # ValidationError rather than DoesNotExist.
            return self._deactivated(f"program {program_id} does not exist")

        if program.runner != Program.FLEETS:
            # get_arguments_storage dispatches on program.runner, so a Ray program
            # would put the arguments where the Fleets submit cannot find them.
            return self._deactivated(f"program {program_id} runner is {program.runner}, expected {Program.FLEETS}")

        if program.disabled:
            return self._deactivated(f"program {program_id} is disabled")

        project = program.code_engine_project
        if project is None:
            # FleetsRunner._get_project raises without one, which would create a
            # FAILED job every loop.
            return self._deactivated(f"program {program_id} has no Code Engine project")

        if not project.active:
            # Same raise, one line below it in _get_project, and a far more likely
            # state: deactivating a project is ordinary operational work.
            return self._deactivated(f"Code Engine project {project.project_name} is not active")

        if not project.cos_bucket_user_data_name:
            # FleetsArgumentsStorage raises ValueError at construction without it.
            return self._deactivated(f"Code Engine project {project.project_name} has no user data COS bucket")

        if program.default_size is None:
            return self._deactivated(f"program {program_id} has no default size")

        if not User.objects.filter(username=settings.FILLER_AUTHOR_USERNAME).exists():
            # Incomplete configuration, not an incident: the chart ships the default
            # username and nobody creates that User row until the feature is prepared.
            return self._deactivated(f"no user with username {settings.FILLER_AUTHOR_USERNAME}")

        return program

    def _deactivated(self, reason: str) -> None:
        """Log the deactivated state, throttled, and return None implicitly.

        Do not add an explicit `return None`: pylint rejects it (R1711).
        """
        self._log_throttled("deactivated", logging.INFO, "[BalanceFillerJobs] deactivated: %s", reason)

    def _discard_unsubmitted_filler_jobs(self) -> None:
        """Stop filler jobs stuck in QUEUED with no fleet.

        Creation submits in the same call that saves the row, so a filler job can
        only sit in QUEUED if something failed in between. Such a row is unusable:
        UpdateFleetsJobsStatuses looks at RUNNING_STATUSES only, so not even the 24h
        timeout can reach it. (get_jobs_to_schedule_fair_share does not filter on
        filler, so ScheduleFleetsJobs may well pick it up first and submit it with
        the SCHEDULE_JOBS context; this path is the safety net for when it does not.)
        """
        stuck = Job.objects.filter(filler=True, status=Job.QUEUED, fleet_id__isnull=True)
        for job in stuck:
            # ERROR, not WARNING: FleetsRunner.submit() sets fleet_id in memory and
            # execute_fleets_job is what persists it, so a failure in between leaves
            # a fleet running in Code Engine that this row can no longer name. There
            # is nothing to cancel, so the operator has to be told to go and look.
            logger.error(
                "[BalanceFillerJobs] job_id=%s filler job was never submitted, discarding it; "
                "check Code Engine for an orphan fleet",
                job.id,
            )
            self._mark_stopped(job)

    def _create_filler_job(self, program: Program, compute_profile: str) -> None:
        """Create and submit one filler job, the most this task creates per loop.

        One per loop rather than the whole shortfall at once. The loop runs about
        once a second, so a four-slot profile is full in four seconds, and the COS
        upload plus the Code Engine submit that each job costs stay off the critical
        path of the status updates that share this single-threaded loop.
        """
        if self._wait_before_retry("create"):
            return
        if self._is_churning():
            # Back off too: the churn count is an unindexed join on api_jobevent, and
            # re-running it every second for the length of an incident is the worst
            # moment to add load. Nothing about a tripped breaker needs re-checking
            # at one hertz.
            self._retry_after["create"] = RETRY_AFTER_LOOPS
            return

        author = User.objects.filter(username=settings.FILLER_AUTHOR_USERNAME).first()
        if author is None:
            # _get_filler_program checked this, so only a deletion in between gets
            # here. Next loop it deactivates cleanly instead of raising.
            return

        if self.kill_signal.received:
            return
        if not self._submit_filler_job(program, compute_profile, author):
            # Whatever broke will still be broken a second from now, so wait before
            # trying again.
            self._retry_after["create"] = RETRY_AFTER_LOOPS

    def _submit_filler_job(self, program: Program, compute_profile: str, author) -> bool:
        """Create and submit one filler job. Return True when it reached PENDING."""
        project = program.code_engine_project
        job = Job(
            program=program,
            author=author,
            filler=True,
            runner=Program.FLEETS,
            compute_profile=compute_profile,
            compute_profile_fk=program.default_size.compute_profile,
            # A filler job is sized by the program's default size, so it records the
            # same provenance a real job resolved that way would.
            size_source=Job.SIZE_SOURCE_DEFAULT_SIZE,
            function_size=program.default_size,
            status=Job.QUEUED,
            env_vars="{}",
            ce_project_name=project.project_name,
            ce_region=project.region,
        )
        # Two steps, two except blocks, because a failure means something different
        # on each side of job.save(): before it there is no row, after it there is a
        # row that only this method can still reach.
        try:
            # Upload the arguments before the row exists, the same order
            # /programs/run uses: a COS failure then leaves no orphan job.
            get_arguments_storage(job).save("{}")
            job.save()
        except DB_EXCEPTIONS:
            # Never swallow these: main.py counts consecutive database failures and
            # restarts the pod, and returning normally here would clear a streak
            # other tasks had accumulated.
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
                # execute_fleets_job raised before it reached runner.submit(), so no
                # fleet exists and this row is already unreachable: nothing ever looks
                # at a QUEUED filler job again. Discarding it here saves a loop for
                # _discard_unsubmitted_filler_jobs, which stays as the safety net for
                # what no except block can reach, a save_direct that fails after the
                # fleet was created and the process dying in between.
                self._mark_stopped(job)
            return self._creation_failed(ex)

        self._clear_throttle("create-error")
        submitted = job.status == Job.PENDING
        self.metrics.increment_filler_jobs_created("submitted" if submitted else "failed")
        logger.info("[BalanceFillerJobs] job_id=%s filler job submitted with status=%s", job.id, job.status)
        return submitted

    def _creation_failed(self, ex: Exception) -> bool:
        """Report a failed creation, throttled, and return False for the caller.

        Caught here rather than in the scheduler's generic handler, which would log a
        traceback once a second. A COS problem, for instance, is a configuration
        fault and not an incident.
        """
        self._log_throttled(
            "create-error", logging.ERROR, "[BalanceFillerJobs] could not create filler job: %s", str(ex)
        )
        self.metrics.increment_filler_jobs_created("failed")
        return False

    def _stop_filler_jobs(self, jobs: list[Job]) -> None:
        """Stop the given filler jobs, cancelling the fleet before writing STOPPED."""
        for job in jobs:
            if self.kill_signal.received:
                return

            key = f"stop:{job.id}"
            if self._wait_before_retry(key):
                continue

            if job.fleet_id:
                try:
                    get_runner(job).stop()
                except RunnerError as ex:
                    # Leave the job active and try again later. Writing STOPPED first
                    # would hide a fleet that is still holding the scarce node, and
                    # the balancer would then create another filler job on top.
                    self._log_throttled(
                        key,
                        logging.ERROR,
                        "[BalanceFillerJobs] job_id=%s error stopping filler job: %s",
                        job.id,
                        str(ex),
                    )
                    self._retry_after[key] = RETRY_AFTER_LOOPS
                    continue

            self._mark_stopped(job)
            logger.info("[BalanceFillerJobs] job_id=%s filler job stopped", job.id)

    def _mark_stopped(self, job: Job) -> None:
        """Write STOPPED on the job, record the event, and count it.

        The counter lives here so that scheduler_filler_jobs_stopped_total always
        equals the number of FILLER_STOP events, which is the natural cross-check
        when reading an incident.
        """
        job.update_fields({"status": Job.STOPPED, "sub_status": None})
        JobEvent.objects.add_status_event(
            job_id=job.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.FILLER_STOP,
            status=Job.STOPPED,
        )
        self.metrics.increment_filler_jobs_stopped()
