"""Scheduling related functions."""

import logging
import random
import time
from typing import List
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Model
from django.db.models import Q
from django.db.models.aggregates import Count, Min

from opentelemetry import trace

from core.config_key import ConfigKey
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from core.models import Job, JobEvent, Program
from core.domain.exceptions.invalid_job_transition_exception import InvalidJobTransitionException
from core.services.job_transitions import JobTransitionService
from core.services.runners import get_runner, RunnerError, RunnerRetryableError
from scheduler.tasks.circuit_breaker import CircuitBreaker

User: Model = get_user_model()
logger = logging.getLogger("scheduler.schedule")

# Jobs whose cancel Code Engine refused, so log_cancel_failure reports each one once.
_REFUSED_CANCEL_WARNED: set[str] = set()
_REFUSED_CANCEL_LIMIT = 10_000


def execute_ray_job(job: Job) -> Job:
    """Executes a Ray job.

    Creates compute resource, connects to cluster, and submits the job.
    Resource cleanup on failure is handled by runner.submit().

    Args:
        job: job to execute

    Returns:
        job of program execution
    """
    tracer = trace.get_tracer("scheduler.tracer")
    with tracer.start_as_current_span("execute.job") as span:
        runner = get_runner(job)

        try:
            runner.submit()
            job.status = Job.PENDING
            if job.compute_resource:
                job.compute_resource.save()
                span.set_attribute("job.clustername", job.compute_resource.title)
        except RunnerError as ex:
            logger.error("job_id=%s error=%s Job set as FAILED: compute resource or submission error", job.id, ex)
            job.status = Job.FAILED
        # Env vars have been forwarded to Ray; wipe them from the DB now.
        job.env_vars = "{}"
        span.set_attribute("job.status", job.status)
    return job


def build_fleets_circuit_breaker() -> CircuitBreaker:
    """A fresh circuit breaker for one Code Engine region, with the thresholds of the Fleets Config entries."""
    return CircuitBreaker(ConfigKey.FLEETS_BREAKER_FAILURES, ConfigKey.FLEETS_BREAKER_PAUSE_SECONDS)


class CodeEngineBreakers:
    """One circuit breaker per Code Engine region, shared by every scheduler call to that region."""

    def __init__(self) -> None:
        self.breakers: dict[str | None, CircuitBreaker] = {}

    def get_breaker(self, region: str | None) -> CircuitBreaker:
        """The circuit breaker for this region (null included), built the first time it is asked for."""
        if region not in self.breakers:
            self.breakers[region] = build_fleets_circuit_breaker()
        return self.breakers[region]

    def paused(self, region: str | None) -> bool:
        """Whether the breaker of this region is open."""
        return self.get_breaker(region).is_open


class FleetsJobSubmitter:
    """Submits Fleets jobs to Code Engine behind one circuit breaker per region, shared by every caller."""

    def __init__(self, transitions: JobTransitionService, breakers: CodeEngineBreakers | None = None):
        self.transitions = transitions
        self.breakers = breakers or CodeEngineBreakers()

    def paused(self, region: str | None) -> bool:
        """Whether the breaker of this region is open."""
        return self.breakers.paused(region)

    def submit(self, job: Job, ctx, *, context: JobEventContext = JobEventContext.SCHEDULE_JOBS) -> Job:
        """Submits a Fleets (Code Engine) job and persists the result.

        Wraps submission under the scheduler.submit trace span propagated from the
        job's env_vars, and writes the status change through the transition service.

        Args:
            job: job to execute
            ctx: OpenTelemetry context extracted from job env_vars
            context: JobEvent context to record for the status change. Defaults to
                SCHEDULE_JOBS, which is what the fair-share scheduler uses; the
                filler-jobs balancer passes FILLER_SUBMIT.

        Returns:
            job with updated status (PENDING on success, FAILED on error)

        Raises:
            RunnerRetryableError: before any write, so the job stays QUEUED.
        """
        breaker = self.breakers.get_breaker(job.ce_region)
        if breaker.is_open:
            raise RunnerRetryableError(f"Fleets submits to region {job.ce_region} are paused by the circuit breaker")
        start = time.monotonic()
        tracer = trace.get_tracer("scheduler.tracer")
        with tracer.start_as_current_span("scheduler.submit", context=ctx) as span:

            runner = get_runner(job)
            try:
                # Fleets runner set only fleet_id
                runner.submit()
                breaker.record_success()
                job.status = Job.PENDING
                transition = self.transitions.queued_to_pending
                logger.info(
                    "[FleetsJobSubmitter] job_id=%s Execute job (%.2fs) set as PENDING",
                    job.id,
                    time.monotonic() - start,
                )
            except RunnerRetryableError:
                breaker.record_failure()
                raise
            except RunnerError as ex:
                logger.error(
                    "[FleetsJobSubmitter] job_id=%s error=%s Job set as FAILED: submission error",
                    job.id,
                    ex,
                )
                job.status = Job.FAILED
                transition = self.transitions.to_failed

            span.set_attribute("job.status", job.status)

            # Env vars have been forwarded to Code Engine; wipe them from the DB now.
            job.env_vars = "{}"
            try:
                transition(
                    job,
                    origin=JobEventOrigin.SCHEDULER,
                    context=context,
                    job_fields={"fleet_id": job.fleet_id, "env_vars": job.env_vars},
                )
            except InvalidJobTransitionException as ex:
                # Lost the race: something else (e.g. a user-initiated stop) already moved this
                # job to a terminal status while it was being submitted. The in-memory job.status
                # set above is returned as-is; the caller reads it, but the DB row was never
                # written since the job is no longer in a state that transition applies to.
                logger.warning("[FleetsJobSubmitter] job_id=%s already in a terminal status: %s", job.id, str(ex))

        return job


class FleetsJobCanceller:
    """Cancels Fleets jobs in Code Engine behind the same per-region breakers the submitter uses."""

    def __init__(self, transitions: JobTransitionService, breakers: CodeEngineBreakers | None = None):
        self.transitions = transitions
        self.breakers = breakers or CodeEngineBreakers()

    def paused(self, region: str | None) -> bool:
        """Whether the breaker of this region is open."""
        return self.breakers.paused(region)

    def cancel(self, job: Job, *, context: JobEventContext) -> bool:
        """Cancel a job's fleet and record STOPPING. ``False`` when there is nothing to cancel.

        One try per tick: a cancel that did not land writes nothing, and a later tick asks again.
        The breaker only learns from a call that reached Code Engine.

        Raises:
            RunnerRetryableError: While the region's breaker is open, or when the cancel did not land.
            RunnerError: When the cancel never left this process, so the region learns nothing.
        """
        if not job.fleet_id:
            # Nothing is sent, so there is nothing for the breaker to learn
            return False

        breaker = self.breakers.get_breaker(job.ce_region)
        if breaker.is_open:
            raise RunnerRetryableError(f"Fleets cancels in region {job.ce_region} are paused by the circuit breaker")
        try:
            cancelled = self.transitions.try_stop(job, origin=JobEventOrigin.SCHEDULER, context=context)
        except RunnerRetryableError:
            breaker.record_failure()
            raise
        breaker.record_success()
        return cancelled


def log_cancel_failure(log: logging.Logger, job: Job, ex: RunnerError, *, prefix: str = "") -> None:
    """Report a cancel that did not land.

    One the region did not answer is a warning every tick, because a later tick usually gets
    through. One it refused is an error on the first tick and debug after, because the caller keeps
    asking for as long as the job is active.
    """
    if isinstance(ex, RunnerRetryableError):
        log.warning("%sjob_id=%s cancel not delivered: %s", prefix, job.id, str(ex))
        return

    message = "%sjob_id=%s fleet_id=%s cancel refused, the job stays active: %s"
    args = (prefix, job.id, job.fleet_id, str(ex))
    if str(job.id) in _REFUSED_CANCEL_WARNED:
        log.debug(message, *args)
        return
    if len(_REFUSED_CANCEL_WARNED) >= _REFUSED_CANCEL_LIMIT:
        _REFUSED_CANCEL_WARNED.clear()
    _REFUSED_CANCEL_WARNED.add(str(job.id))
    log.error(message, *args)


def get_jobs_to_schedule_fair_share(slots: int, gpu: bool, runner: str = Program.RAY) -> List[Job]:
    """Returns jobs for execution based on fair share distribution of resources.

    Args:
        slots: max number of users to query
        gpu: filter jobs by GPU requirement
        runner: filter jobs by runner type

    Returns:
        list of jobs for execution
    """

    # maybe refactor this using big SQL query :thinking:

    max_limit = min(slots, settings.LIMITS_MAX_FLEETS)

    # Per-user concurrency is tracked independently per runner: Fleets and Ray
    # have separate limits and separate running-job tallies, so a user's Fleets
    # jobs don't count against their Ray budget and vice versa.
    if runner == Program.FLEETS:
        jobs_per_user = settings.LIMITS_JOBS_PER_USER_FLEETS
    else:
        jobs_per_user = settings.LIMITS_JOBS_PER_USER

    # Filler jobs are not user demand, and they belong to the author of the filler
    # function, so counting them would stop that person's own jobs being promoted.
    # This one query serves both LIMITS_JOBS_PER_USER and its Fleets variant.
    running_jobs_per_user = (
        Job.objects.filter(status__in=Job.RUNNING_STATUSES, runner=runner)
        .exclude(filler=True)
        .values("author")
        .annotate(running_jobs_count=Count("id"))
    )

    users_at_max_capacity = [
        entry["author"] for entry in running_jobs_per_user if entry["running_jobs_count"] >= jobs_per_user
    ]

    author_date_pull = (
        Job.objects.filter(status=Job.QUEUED, gpu=gpu, runner=runner)
        .exclude(author__in=users_at_max_capacity)
        .values("author")
        .annotate(job_date=Min("created"))[:max_limit]
    )

    if len(author_date_pull) == 0:
        return []

    author_date_list = list(author_date_pull)
    if len(author_date_pull) >= slots:
        author_date_list = random.sample(author_date_list, k=slots)

    job_filter = Q()
    for entry in author_date_list:
        job_filter |= Q(author=entry["author"]) & Q(created=entry["job_date"])

    return Job.objects.filter(job_filter)


def check_job_timeout(job: Job):
    """Check job timeout and update job status."""

    if job.status in Job.RUNNING_STATUSES:
        timeout = settings.PROGRAM_TIMEOUT
        latest_job_event = JobEvent.objects.filter(job=job).order_by("-created").first()
        if not latest_job_event:
            # This should never happen since every job should have at least 1 JobEvent (on creation).
            latest_job_event = job.created
        endtime = latest_job_event.created + timedelta(hours=timeout)
        now = datetime.now(tz=endtime.tzinfo)
        if endtime < now:
            logger.warning(
                "job_id=%s cluster=%s timeout=%s hours: job stopped.",
                job.id,
                job.compute_resource.title,
                timeout,
            )
            # The job has exceeded the maximum duration allowed.
            return True

    return False


def fail_job_insufficient_resources(job: Job):
    """Fail job if insufficient resources are available."""
    if settings.RAY_CLUSTER_NO_DELETE_ON_COMPLETE:
        logger.debug(
            "job_id=%s cluster=%s RAY_CLUSTER_NO_DELETE_ON_COMPLETE enabled, cluster not removed",
            job.id,
            job.compute_resource.title,
        )
    else:
        runner = get_runner(job)
        try:
            runner.free_resources()
        except RunnerError:
            pass
        job.compute_resource.delete()
        job.compute_resource = None

    return Job.FAILED
