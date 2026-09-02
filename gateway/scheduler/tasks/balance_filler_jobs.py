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

# Loops to skip after a failed creation before trying again.
#
# Why the retry exists at all: this task keeps no memory of what it tried. Every loop
# it looks at the world, works out what is missing, and acts. A failure leaves the
# world exactly as it was, so the next loop reaches the same conclusion and repeats the
# same attempt a second later, and the one after that too. Nobody schedules those
# retries, they fall out of the loop, and this counter is the only memory the loop has
# to hold them back.
#
# What it saves is real work rather than log volume. One attempt costs a COS upload and
# a Code Engine submit, and when the submit is what failed it also leaves a row behind
# in FAILED with its status event, so a broken dependency would mean about 86,000 of
# those a day. This loop is single-threaded and shared with the status-update tasks, so
# spending it on doomed calls also delays the promotion of real jobs. Sixty loops brings
# it down to about 1,400 attempts a day, and it spaces the retry out rather than giving
# up, so the first attempt after a fix fills the slots with nobody having to intervene.
#
# It counts loops, not seconds, and the countdown only advances on loops that reach the
# creation path, so the delay pauses while real jobs fill the slots instead of expiring
# during a period when nothing was being attempted.
RETRY_AFTER_LOOPS = 60


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
        # Nothing is protecting a profile now, so the target is zero and the
        # occupancy series go away rather than claim a measurement nobody took.
        self.metrics.set_filler_profile_slots(0)
        self.metrics.clear_filler_profile_jobs()
        if filler_jobs:
            logger.debug("[BalanceFillerJobs] stopping %s filler job(s), the feature is off", len(filler_jobs))
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
        # DEBUG because this runs every second and says the same thing every time. The
        # numbers an operator needs are in scheduler_filler_profile_slots and
        # scheduler_filler_profile_jobs, set just below.
        logger.debug(
            "[BalanceFillerJobs] profile=%s slots=%s real_running=%s target=%s",
            compute_profile,
            slots,
            real_running,
            target,
        )
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

        if stale:
            logger.debug(
                "[BalanceFillerJobs] stopping %s filler job(s) on another program or compute profile", len(stale)
            )
            self._stop_filler_jobs(stale)

        if len(current) < target:
            self._create_filler_job(program, compute_profile)
        elif len(current) > target:
            self._stop_filler_jobs(current[: len(current) - target])

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

        program = self._lookup_filler_function()
        if program is None:
            return None

        if program.runner != Program.FLEETS:
            # get_arguments_storage dispatches on program.runner, so a Ray program
            # would put the arguments where the Fleets submit cannot find them.
            return self._deactivated(f"function {program} runner is {program.runner}, expected {Program.FLEETS}")

        if program.disabled:
            return self._deactivated(f"function {program} is disabled")

        project = program.code_engine_project
        if project is None:
            # FleetsRunner._get_project raises without one, which would create a
            # FAILED job every loop.
            return self._deactivated(f"function {program} has no Code Engine project")

        if not project.active:
            # Same raise, one line below it in _get_project, and a far more likely
            # state: deactivating a project is ordinary operational work.
            return self._deactivated(f"Code Engine project {project.project_name} is not active")

        if not project.cos_bucket_user_data_name:
            # FleetsArgumentsStorage raises ValueError at construction without it.
            return self._deactivated(f"Code Engine project {project.project_name} has no user data COS bucket")

        if program.default_size is None:
            return self._deactivated(f"function {program} has no default size")

        return program

    def _lookup_filler_function(self) -> Program | None:
        """Return the Program the config key names, or None after saying why it cannot.

        The key takes either form: with a slash it is ``provider/title``, and without
        one it is the Program's id.

        The two are not equivalent, and what separates them is who can update the
        function afterwards. Matching on provider__name requires the function to belong
        to a provider, and upload permission on a provider function comes from write
        access to the provider rather than from authorship, so anyone on the team can
        push a new version with their own API key. An id can just as well name a
        personal function, and updating one of those means being its author, so the
        feature then depends on one person's key. That is an operator's choice rather
        than a fault, but the id form gives that property up. Either way the filler
        jobs are owned by the function's author, so they appear in that person's job
        list.

        Split out from _get_filler_program so that reading the value, checking its shape
        and resolving it stay together, and so that method keeps one branch per check.
        """
        value = Config.get(ConfigKey.FILLER_FUNCTION).strip()
        if not value:
            return self._deactivated(f"{ConfigKey.FILLER_FUNCTION.value} is empty")

        programs = Program.objects.select_related("default_size__compute_profile", "code_engine_project")
        try:
            if "/" in value:
                # The provider/title convention already has a parser in api.utils
                # (parse_title_and_provider), but the import-linter contracts forbid
                # scheduler from importing api, so it is split by hand here. The
                # duplication is deliberate.
                parts = value.split("/")
                if len(parts) != 2 or not all(parts):
                    return self._deactivated(
                        f"{ConfigKey.FILLER_FUNCTION.value} is {value!r}, expected provider/title or an id"
                    )
                # get(), not filter().first(): the unique_provider_title constraint on
                # (provider, title) makes at most one row match, so there is no ambiguity
                # to resolve here and MultipleObjectsReturned cannot happen.
                return programs.get(provider__name=parts[0], title=parts[1])
            return programs.get(id=value)
        except Program.DoesNotExist:
            return self._deactivated(f"function {value} does not exist")
        except ValidationError:
            # Only the id branch reaches this. Program.id is a UUIDField, so a value
            # that is not a UUID raises ValidationError while the field is cleaned,
            # before any query runs, and never DoesNotExist. Measured on this code:
            # get(id="not-a-uuid") raises ValidationError('"not-a-uuid" is not a valid
            # UUID.'). Without this the scheduler would log a traceback once a second
            # instead of deactivating and saying which value is wrong.
            return self._deactivated(f"{ConfigKey.FILLER_FUNCTION.value} is {value!r}, which is not a function id")

    def _deactivated(self, reason: str) -> None:
        """Log why the feature is not active and return None implicitly.

        Do not add an explicit `return None`: pylint rejects it (R1711).
        """
        logger.debug("[BalanceFillerJobs] deactivated: %s", reason)

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
            # The filler jobs belong to whoever owns the function they run. Nothing in
            # this task reads the author, and the balancer excludes filler jobs from
            # billing, from the metrics and from the fair-share tally, so a dedicated
            # service user would buy nothing over the one the function already has.
            author=program.author,
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

        submitted = job.status == Job.PENDING
        self.metrics.increment_filler_jobs_created("submitted" if submitted else "failed")
        logger.info("[BalanceFillerJobs] job_id=%s filler job submitted with status=%s", job.id, job.status)
        # A submit that came back without reaching PENDING swallowed a RunnerError
        # inside execute_fleets_job, so it is a failure like any other here.
        return submitted

    def _creation_failed(self, ex: Exception) -> bool:
        """Report a failed creation and give the caller the value to return.

        Reported here rather than left to the scheduler's generic handler, which would
        log a traceback once a second. Unconditional: RETRY_AFTER_LOOPS already limits
        this to one line a minute, because the line is only written when an attempt is
        made.
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
                # Leave the job active and try again next loop. Writing STOPPED
                # first would hide a fleet that is still holding the scarce node, and
                # the balancer would then create another filler job on top.
                logger.error("[BalanceFillerJobs] job_id=%s error stopping filler job: %s", job.id, str(ex))
                return

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
