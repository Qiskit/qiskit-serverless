"""Keep a minimum number of jobs running on a scarce Fleets compute profile."""

import logging
from dataclasses import dataclass
from enum import auto, Enum
from functools import partial
from typing import Callable

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

# Loops to skip after a failure before trying the same thing again.
#
# Why the retry exists at all: this task keeps no memory of what it tried. Every loop
# it looks at the world, works out what is missing, and acts. A failure leaves the
# world exactly as it was, so the next loop reaches the same conclusion and repeats
# the same attempt a second later, and the one after that too. Nobody schedules those
# retries, they fall out of the loop, and this delay is the only memory the loop has
# to hold them back.
#
# So this is not about log volume, it is about real work. One creation attempt costs a
# COS upload, a Code Engine submit, and a row written and then marked STOPPED; one
# stop attempt costs a fleet cancellation call. At one loop a second a broken
# dependency would mean about 86,000 of those a day, and because this loop is
# single-threaded and shared with the status-update tasks, spending it on doomed calls
# delays the promotion of real jobs. Sixty loops brings that down to about 1,400
# attempts a day.
#
# It spaces the retry out, it does not give up: the balancer keeps trying for as long
# as the cause lasts, so the first attempt after a fix succeeds and the slots fill
# with nobody having to touch anything. Nothing in this balancer gives up any more.
# The one thing that did was the churn breaker, and it was removed in favour of the
# scheduler_filler_jobs_ended_total metric.
#
# It counts loops, not seconds, and the countdown only advances on loops that reach
# the same code path, so a creation delay pauses while real jobs fill the slots
# instead of expiring during a period when nothing was being attempted.
RETRY_AFTER_LOOPS = 60


class _Attempt(Enum):
    """What one run of a throttled piece of work did.

    FAILED is the only outcome that starts a backoff. SKIPPED exists because not
    reaching the work is not the same as the work failing: a shutdown signal or a
    vanished author must not buy a minute of silence for a dependency that may be
    perfectly healthy.

    There is deliberately no outcome for work that is still going, because nothing
    here waits for anything to finish. A filler job that was submitted but has not
    started running yet sits in PENDING, and PENDING is one of RUNNING_STATUSES, so it
    already counts as occupancy and the balancer sees no shortfall to fill on top of
    it. That is the occupancy count holding the slot, not this class.
    """

    DONE = auto()
    FAILED = auto()
    SKIPPED = auto()


class _Key(str, Enum):
    """The fixed throttling keys of this task, so a typo is an error and not silence.

    A key is only a name to index state under. These are the conditions of the task
    as a whole; state that belongs to one job is keyed by _Throttle._job_key.

    The two halves of _KeyState never meet on the same fixed key, and that is load
    bearing. Only CREATE ever carries a delay, and only STATUS, STALE, DRAIN,
    DEACTIVATED and CREATE_ERROR are ever cleared, so "forgetting what was said cannot
    cancel a delay" holds by construction and not merely because _clear happens to
    touch one field today. Folding CREATE and CREATE_ERROR into a single key, which
    looks like an obvious tidy-up, is what would break it: clearing the report after a
    successful creation would then reach the backoff of a failed one.
    """

    STATUS = "status"
    DEACTIVATED = "deactivated"
    DRAIN = "drain"
    STALE = "stale"
    CREATE_ERROR = "create-error"
    CREATE = "create"


_JOB_KEY_PREFIX = "stop:"


@dataclass
class _KeyState:
    """The two halves of one key's throttling state, which are worth different things.

    last_args is what the key logged last. It changes only what gets printed: the
    balancer does exactly the same work with it or without it. What it buys is a log
    pipeline that is readable, instead of tens of thousands of identical lines a day
    burying everything else.

    retry_loops is how many loops the key still owes before its work is attempted
    again. That one avoids real work: COS uploads, Code Engine submits and fleet
    cancellations that are going to fail again a second from now (see
    RETRY_AFTER_LOOPS).

    They live in one entry because they are always indexed by the same key, not
    because one implies the other, and that is why forgetting what was said never
    cancels a backoff: being worth reporting again says nothing about being due
    again.
    """

    last_args: tuple | None = None
    retry_loops: int = 0


class _Throttle:
    """Everything this task says out loud, and how often it retries what failed.

    The task hands over facts ("balancing on this profile", "this creation failed")
    and this class decides the level, whether the line is a repeat, and which other
    conditions the fact invalidates. Callers never name a key, so a key cannot be
    misspelled on one side of a pair, and the mutual invalidation between the
    balancing and drained states is an invariant here rather than a convention
    spread over the call sites.
    """

    def __init__(self):
        self._state: dict[str, _KeyState] = {}

    # -- Reporting ------------------------------------------------------------------
    #
    # These only decide what gets printed and at which level. None of them changes
    # what the balancer does: it takes the same actions whether or not a line was
    # suppressed as a repeat.

    def balancing(self, profile: str, slots: int, real_running: int, target: int) -> None:
        """Report the state of a loop that is balancing a profile.

        The arguments are the throttle: the line speaks at INFO again the moment any
        of these four numbers moves, which is when an operator wants to see it, and
        stays quiet while the platform is idle. Being here at all means the feature
        is on, so the two states that say otherwise are made reportable again.
        """
        self._log(
            _Key.STATUS,
            logging.INFO,
            "[BalanceFillerJobs] profile=%s slots=%s real_running=%s target=%s",
            profile,
            slots,
            real_running,
            target,
        )
        self._clear(_Key.DRAIN)
        self._clear(_Key.DEACTIVATED)

    def drained(self, count: int) -> None:
        """Report the cleanup of `count` filler jobs because the feature is off.

        Nothing to stop is not an event, so a zero only makes the line reportable
        again. Either way the balancing state is made reportable again, so switching
        the feature back on is never silent.
        """
        self._clear(_Key.STATUS)
        self._clear(_Key.STALE)
        if count:
            self._log(
                _Key.DRAIN,
                logging.INFO,
                "[BalanceFillerJobs] stopping %s filler job(s), the feature is off",
                count,
            )
        else:
            self._clear(_Key.DRAIN)

    def deactivated(self, reason: str) -> None:
        """Report why the feature is not active. The reason is the throttle."""
        self._log(_Key.DEACTIVATED, logging.INFO, "[BalanceFillerJobs] deactivated: %s", reason)

    def stale(self, count: int) -> None:
        """Report `count` filler jobs stopped for belonging to another program or profile.

        A zero is the normal case and not an event, so it only makes the line
        reportable again for the next time it happens.
        """
        if count:
            self._log(
                _Key.STALE,
                logging.INFO,
                "[BalanceFillerJobs] stopping %s filler job(s) on another program or compute profile",
                count,
            )
        else:
            self._clear(_Key.STALE)

    def create_ok(self) -> None:
        """Note that a creation worked, so the next failure is reported at ERROR."""
        self._clear(_Key.CREATE_ERROR)

    def create_failed(self, ex: Exception) -> None:
        """Report a creation failure at ERROR, once per distinct message.

        Reported here rather than left to the scheduler's generic handler, which
        would log a traceback once a second. A COS misconfiguration is a
        configuration fault, not an incident. A different message is a different
        symptom, so it speaks again.
        """
        self._log(_Key.CREATE_ERROR, logging.ERROR, "[BalanceFillerJobs] could not create filler job: %s", str(ex))

    def stop_failed(self, job_id, ex: Exception) -> None:
        """Report at ERROR that this job's fleet would not cancel.

        Keyed by the job, the same way its backoff is, so one stuck fleet neither
        silences another nor delays it.
        """
        self._log(
            self._job_key(job_id),
            logging.ERROR,
            "[BalanceFillerJobs] job_id=%s error stopping filler job: %s",
            job_id,
            str(ex),
        )

    # -- Retrying -------------------------------------------------------------------
    #
    # These two do change what the balancer does, by not doing it: for the length of a
    # delay the work is simply not attempted. That is the half worth having, and
    # RETRY_AFTER_LOOPS explains why the work would otherwise repeat every second.

    def attempt_create(self, work: Callable[[], _Attempt]) -> None:
        """Run `work` unless a creation delay is pending, and start one if it fails.

        What this spaces out is a COS upload followed by a Code Engine submit, so a
        broken one of either costs one attempt a minute instead of one a second.
        """
        self._attempt(_Key.CREATE, work)

    def attempt_stop(self, job_id, work: Callable[[], _Attempt]) -> None:
        """Run `work` unless this job's stop delay is pending, and start one if it fails.

        What this spaces out is a fleet cancellation call, and the delay is per job, so
        one fleet that will not cancel costs one call a minute and holds up no other
        job in the same loop.
        """
        self._attempt(self._job_key(job_id), work)

    def forget_jobs(self, live_ids) -> None:
        """Drop the state of every job outside `live_ids`, so it cannot grow forever.

        The state lives as long as the process and filler jobs come and go, so
        without this the dict would keep an entry per job the balancer ever stopped.
        """
        live = {self._job_key(job_id) for job_id in live_ids}
        for key in [k for k in self._state if k.startswith(_JOB_KEY_PREFIX) and k not in live]:
            del self._state[key]

    # -- Internals -------------------------------------------------------------

    @staticmethod
    def _job_key(job_id) -> str:
        """Return the key that holds one job's state, so no caller ever builds it."""
        return f"{_JOB_KEY_PREFIX}{job_id}"

    def _log(self, key: str, level: int, message: str, *args) -> None:
        """Log at `level` when this key's arguments change, at DEBUG when they repeat."""
        entry = self._state.setdefault(key, _KeyState())
        if entry.last_args != args:
            logger.log(level, message, *args)
            entry.last_args = args
        else:
            logger.debug(message, *args)

    def _clear(self, key: str) -> None:
        """Forget what `key` last said, leaving any backoff of its own untouched."""
        entry = self._state.get(key)
        if entry is not None:
            entry.last_args = None

    def _attempt(self, key: str, work: Callable[[], _Attempt]) -> None:
        """Serve out `key`'s delay, otherwise run `work` and start a delay if it failed.

        Only a failure creates state, so a key that never fails never takes up an
        entry.
        """
        entry = self._state.get(key)
        if entry is not None and entry.retry_loops > 0:
            # The countdown advances here, so it only moves on loops that got this far.
            entry.retry_loops -= 1
            return
        if work() is _Attempt.FAILED:
            self._state.setdefault(key, _KeyState()).retry_loops = RETRY_AFTER_LOOPS


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
        self.throttle = _Throttle()

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
        # Nothing is protecting a profile now, so the target is zero and the
        # occupancy series go away rather than claim a measurement nobody took.
        self.metrics.set_filler_profile_slots(0)
        self.metrics.clear_filler_profile_jobs()
        self.throttle.drained(len(filler_jobs))
        self._stop_filler_jobs(filler_jobs)

    def _balance_filler_jobs(self, program: Program, filler_jobs: list[Job]) -> None:
        """Stop the filler jobs that no longer belong, then close the gap to the target."""
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
        self.throttle.balancing(compute_profile, slots, real_running, target)
        self.metrics.set_filler_profile_slots(slots)
        self.metrics.set_filler_profile_jobs(real_running, "real")

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
        # Reported after the split and before this loop acts, so the gauge is the
        # occupancy the decisions below were taken on.
        self.metrics.set_filler_profile_jobs(len(current), "filler")

        self.throttle.stale(len(stale))
        self._stop_filler_jobs(stale)

        if len(current) < target:
            self._create_filler_job(program, compute_profile)
        elif len(current) > target:
            self._stop_filler_jobs(current[: len(current) - target])

    def _forget_finished_jobs(self, filler_jobs: list[Job]) -> None:
        """Drop the throttling state of jobs that are no longer active."""
        self.throttle.forget_jobs({job.id for job in filler_jobs})

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
        self.throttle.deactivated(reason)

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
        self.throttle.attempt_create(partial(self._resolve_author_and_submit, program, compute_profile))

    def _resolve_author_and_submit(self, program: Program, compute_profile: str) -> _Attempt:
        """Resolve the author, honour a shutdown, and submit one filler job.

        Both checks live inside the attempt rather than in front of it, so the author
        query is not run on the loops that are only serving out a delay. Neither is a
        failure of the work, so both report SKIPPED and buy no backoff.
        """
        author = User.objects.filter(username=settings.FILLER_AUTHOR_USERNAME).first()
        if author is None:
            # _get_filler_program checked this, so only a deletion in between gets
            # here. Next loop it deactivates cleanly instead of raising.
            return _Attempt.SKIPPED

        if self.kill_signal.received:
            return _Attempt.SKIPPED

        return self._submit_filler_job(program, compute_profile, author)

    def _submit_filler_job(self, program: Program, compute_profile: str, author) -> _Attempt:
        """Create and submit one filler job. DONE when it reached PENDING."""
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

        self.throttle.create_ok()
        submitted = job.status == Job.PENDING
        self.metrics.increment_filler_jobs_created("submitted" if submitted else "failed")
        logger.info("[BalanceFillerJobs] job_id=%s filler job submitted with status=%s", job.id, job.status)
        # A submit that came back without reaching PENDING swallowed a RunnerError
        # inside execute_fleets_job, so it is a failure like any other here.
        return _Attempt.DONE if submitted else _Attempt.FAILED

    def _creation_failed(self, ex: Exception) -> _Attempt:
        """Report a failed creation and give the caller the outcome to return."""
        self.throttle.create_failed(ex)
        self.metrics.increment_filler_jobs_created("failed")
        return _Attempt.FAILED

    def _stop_filler_jobs(self, jobs: list[Job]) -> None:
        """Stop the given filler jobs, cancelling the fleet before writing STOPPED."""
        for job in jobs:
            if self.kill_signal.received:
                return
            self.throttle.attempt_stop(job.id, partial(self._stop_one_filler_job, job))

    def _stop_one_filler_job(self, job: Job) -> _Attempt:
        """Cancel this job's fleet if it has one, then write STOPPED on the row."""
        if job.fleet_id:
            try:
                get_runner(job).stop()
            except RunnerError as ex:
                # Leave the job active and try again later. Writing STOPPED first
                # would hide a fleet that is still holding the scarce node, and the
                # balancer would then create another filler job on top.
                self.throttle.stop_failed(job.id, ex)
                return _Attempt.FAILED

        self._mark_stopped(job)
        logger.info("[BalanceFillerJobs] job_id=%s filler job stopped", job.id)
        return _Attempt.DONE

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
