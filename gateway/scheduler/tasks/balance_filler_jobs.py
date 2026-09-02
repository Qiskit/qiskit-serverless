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

# A COS upload plus a Code Engine submit per job, on the single-threaded scheduler
# loop: cap them so a mistyped slot count cannot block status updates for minutes.
MAX_SUBMITS_PER_LOOP = 4

# Sanity cap on FILLER_SLOTS, which is free text in the admin. Filler jobs count
# against LIMITS_MAX_FLEETS, so a mistyped few hundred would starve every real
# Fleets job on the platform.
MAX_SLOTS = 16

# Loops to skip after a failure before trying the same thing again, which turns
# tens of thousands of doomed retries a day into about 1,400. It counts loops, not
# seconds: the countdown only advances on loops that reach the same code path, so a
# creation delay pauses while real jobs fill the slots.
RETRY_AFTER_LOOPS = 60

# Churn breaker. A filler job that ends on its own (FAILED because the submit was
# rejected, or SUCCEEDED because the program exited) is replaced a second later,
# forever, with nothing counting it. STOPPED is excluded: that is the balancer
# making room for real work, or the 24h timeout, and both are the feature working.
CHURN_WINDOW = timedelta(minutes=5)
CHURN_LIMIT = 5


class BalanceFillerJobs(SchedulerTask):
    """Keep real plus filler jobs on one compute profile at the configured minimum.

    The compute profile is not configured directly: it is derived from the filler
    program's default size, so it cannot drift away from the program it belongs to.

    Filler jobs skip the queue that ScheduleFleetsJobs feeds. Fair-share picks at
    most one queued job per author per loop and every filler job shares one author,
    so filling four slots through the queue would take four loops and would compete
    with real queued jobs for the same slots.
    """

    def __init__(self, kill_signal: KillSignal, metrics: SchedulerMetrics):
        self.kill_signal = kill_signal
        self.metrics = metrics
        self._last_logged: dict[str, tuple] = {}
        self._retry_after: dict[str, int] = {}

    def run(self):
        """Create or stop filler jobs so the configured minimum is met."""
        self._discard_unsubmitted_filler_jobs()

        program = self._get_filler_program()
        target = 0
        compute_profile = None
        if program is None:
            self._clear_throttle("status")
        if program is not None:
            self._clear_throttle("deactivated")
            compute_profile = self._compute_profile_of(program)
            slots = self._slots()
            real_running = Job.objects.filter(
                compute_profile=compute_profile,
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

        filler_jobs = list(Job.objects.filter(filler=True, status__in=Job.RUNNING_STATUSES).order_by("created"))

        # A filler job on any other compute profile holds capacity nobody asked it
        # to hold, so it is always stopped. This is also what cleans everything up
        # when the feature is off, because then there is no derived profile to match.
        stale = [job for job in filler_jobs if job.compute_profile != compute_profile]
        current = [job for job in filler_jobs if job.compute_profile == compute_profile]

        if stale:
            self._log_throttled(
                "stale",
                logging.INFO,
                "[BalanceFillerJobs] stopping %s filler job(s) on another compute profile",
                len(stale),
            )
            self._stop_filler_jobs(stale)
        else:
            self._clear_throttle("stale")

        if len(current) < target:
            self._create_filler_jobs(program, compute_profile, target - len(current))
        elif len(current) > target:
            self._stop_filler_jobs(current[: len(current) - target])

        self._forget_finished_jobs(filler_jobs)

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

    def _slots(self) -> int:
        """Return the configured slot count, clamped to MAX_SLOTS."""
        slots = Config.get_int(ConfigKey.FILLER_SLOTS)
        if slots < 0:
            self._log_throttled(
                "negative-slots",
                logging.WARNING,
                "[BalanceFillerJobs] %s is %s, treating it as 0",
                ConfigKey.FILLER_SLOTS.value,
                slots,
            )
            return 0
        if slots > MAX_SLOTS:
            self._log_throttled(
                "clamp",
                logging.WARNING,
                "[BalanceFillerJobs] %s is %s, clamped to MAX_SLOTS=%s",
                ConfigKey.FILLER_SLOTS.value,
                slots,
                MAX_SLOTS,
            )
            return MAX_SLOTS
        self._clear_throttle("clamp")
        return slots

    def _compute_profile_of(self, program: Program) -> str:
        """Return the program's default compute profile in canonical form.

        ComputeProfile primary keys are free text with no validation anywhere, so a
        row can carry the prefixed form. Jobs always store the prefix-less form, so
        normalizing here is what makes the comparison with real jobs meaningful.
        The same normalized value is written on the filler jobs this task creates,
        so that the next loop recognizes them as its own.
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
        recent_deaths = JobEvent.objects.filter(
            job__filler=True,
            data__status__in=[Job.FAILED, Job.SUCCEEDED],
            created__gte=datetime.now(timezone.utc) - CHURN_WINDOW,
        ).count()
        if recent_deaths < CHURN_LIMIT:
            self._clear_throttle("churn")
            return False
        self._log_throttled(
            "churn",
            logging.ERROR,
            "[BalanceFillerJobs] %s filler jobs created in the last %s ended on their own; "
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

    def _create_filler_jobs(self, program: Program, compute_profile: str, count: int) -> None:
        """Create and submit up to MAX_SUBMITS_PER_LOOP filler jobs for the program."""
        if self._wait_before_retry("create") or self._is_churning():
            return

        author = User.objects.filter(username=settings.FILLER_AUTHOR_USERNAME).first()
        if author is None:
            # _get_filler_program checked this, so only a deletion in between gets
            # here. Next loop it deactivates cleanly instead of raising.
            return

        for _ in range(min(count, MAX_SUBMITS_PER_LOOP)):
            if self.kill_signal.received:
                return
            if not self._create_one_filler_job(program, compute_profile, author):
                # Whatever broke will still be broken for the next one in this same
                # loop, so stop here and wait before trying again.
                self._retry_after["create"] = RETRY_AFTER_LOOPS
                return

    def _create_one_filler_job(self, program: Program, compute_profile: str, author) -> bool:
        """Create and submit one filler job. Return True when it reached PENDING."""
        project = program.code_engine_project
        job = Job(
            program=program,
            author=author,
            filler=True,
            runner=Program.FLEETS,
            compute_profile=compute_profile,
            compute_profile_fk=program.default_size.compute_profile,
            status=Job.QUEUED,
            env_vars="{}",
            ce_project_name=project.project_name,
            ce_region=project.region,
        )
        try:
            # Upload the arguments before the row exists, the same order
            # /programs/run uses: a COS failure then leaves no orphan job.
            get_arguments_storage(job).save("{}")
            job.save()
            job = execute_fleets_job(
                job,
                TraceContextTextMapPropagator().extract(carrier={}),
                context=JobEventContext.FILLER_SUBMIT,
            )
        except DB_EXCEPTIONS:
            # Never swallow these: main.py counts consecutive database failures and
            # restarts the pod, and returning normally here would clear a streak
            # other tasks had accumulated.
            raise
        except Exception as ex:  # pylint: disable=broad-exception-caught
            # Everything is caught here rather than in the scheduler's generic
            # handler, which would log a traceback once a second. A COS problem, for
            # instance, is a configuration fault and not an incident.
            self._log_throttled(
                "create-error", logging.ERROR, "[BalanceFillerJobs] could not create filler job: %s", ex
            )
            self.metrics.increment_filler_jobs_created("failed")
            return False

        self._clear_throttle("create-error")
        submitted = job.status == Job.PENDING
        self.metrics.increment_filler_jobs_created("submitted" if submitted else "failed")
        logger.info("[BalanceFillerJobs] job_id=%s filler job submitted with status=%s", job.id, job.status)
        return submitted

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
                        ex,
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
