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
from core.models import BlockedCloudResource, Job, JobEvent, Program
from core.domain.exceptions.invalid_job_transition_exception import InvalidJobTransitionException
from core.services.job_transitions import FleetAppearedError, JobTransitionService
from core.services.runners import get_runner, AbstractRunner, RunnerError, RunnerRetryableError
from scheduler.tasks.circuit_breaker import CircuitBreaker

User: Model = get_user_model()
logger = logging.getLogger("scheduler.schedule")

# Jobs whose cancel was refused, so first_cancel_refusal reports each one once.
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

    def submit(self, job: Job, ctx, *, context: JobEventContext = JobEventContext.SCHEDULE_JOBS) -> None:
        """Submit a Fleets (Code Engine) job and persist the result.

        Wraps submission under the scheduler.submit trace span propagated from the job's env_vars,
        and writes the status change through the transition service. The fleet is recorded as soon
        as it exists, before any status write and outside the transition's transaction, so a row
        that left QUEUED meanwhile still points at its fleet instead of orphaning it.

        Args:
            job: job to execute
            ctx: OpenTelemetry context extracted from job env_vars
            context: JobEvent context to record for the status change. Defaults to
                SCHEDULE_JOBS, which is what the fair-share scheduler uses; the
                filler-jobs balancer passes FILLER_SUBMIT.

        Returns nothing: it returns only when the job reached PENDING, and raises otherwise.

        Raises:
            RunnerRetryableError: nothing was written, so the job is still QUEUED and a later tick
                can try again.
            RunnerError: Code Engine refused the submit. The job is already FAILED, with the
                reason on an error event.
            InvalidJobTransitionException: the row left QUEUED while it was being submitted, so the
                fleet created for it has been cancelled.
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
            except RunnerRetryableError:
                breaker.record_failure()
                raise
            except RunnerError as ex:
                logger.error(
                    "[FleetsJobSubmitter] job_id=%s error=%s Job set as FAILED: submission error",
                    job.id,
                    ex,
                )
                JobEvent.objects.add_error_event(
                    job_id=job.id,
                    origin=JobEventOrigin.SCHEDULER,
                    context=context,
                    code="FLEET_SUBMIT_FAILED",
                    message="The job could not be submitted to Code Engine",
                    exception=type(ex).__name__,
                    args=str(ex),
                )
                job.update_fields({"env_vars": "{}"})
                try:
                    self.transitions.to_failed(job, origin=JobEventOrigin.SCHEDULER, context=context)
                except InvalidJobTransitionException as refused:
                    logger.warning("[FleetsJobSubmitter] job_id=%s already in a terminal status: %s", job.id, refused)
                span.set_attribute("job.status", job.status)
                raise

            # Recorded on its own, before any status write
            job.update_fields({"fleet_id": job.fleet_id, "env_vars": "{}"})
            try:
                self.transitions.queued_to_pending(job, origin=JobEventOrigin.SCHEDULER, context=context)
            except InvalidJobTransitionException as refused:
                logger.warning(
                    "[FleetsJobSubmitter] job_id=%s left QUEUED while submitting, cancelling fleet_id=%s: %s",
                    job.id,
                    job.fleet_id,
                    refused,
                )
                self._cancel_orphan_fleet(job, runner, context)
                span.set_attribute("job.status", job.status)
                raise

            span.set_attribute("job.status", job.status)
            logger.info(
                "[FleetsJobSubmitter] job_id=%s Execute job (%.2fs) set as PENDING",
                job.id,
                time.monotonic() - start,
            )

    @staticmethod
    def _cancel_orphan_fleet(job: Job, runner: AbstractRunner, context: JobEventContext) -> None:
        """Cancel a fleet whose row reached a terminal status while it was being submitted."""
        try:
            if not runner.stop():
                logger.error(
                    "[FleetsJobSubmitter] job_id=%s fleet_id=%s had nothing to cancel, check Code Engine",
                    job.id,
                    job.fleet_id,
                )
        except (RunnerRetryableError, RunnerError) as ex:
            logger.error(
                "[FleetsJobSubmitter] job_id=%s fleet_id=%s is still running, its cancel failed: %s",
                job.id,
                job.fleet_id,
                str(ex),
            )
            # Nothing will retry this: the row is terminal, so no scheduler task reads it again.
            JobEvent.objects.add_error_event(
                job_id=job.id,
                origin=JobEventOrigin.SCHEDULER,
                context=context,
                code="FLEET_LEFT_RUNNING",
                message=f"Fleet {job.fleet_id} was created but could not be cancelled",
                exception=type(ex).__name__,
                args=str(ex),
            )


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
            FleetAppearedError: When the job's fleet_id changed under this call. Nothing is written.
            RunnerError: When the job's project is unusable, or the cancel never left this process.
            InvalidJobTransitionException: When the cancel landed but the row had already left a
                status STOPPING is reachable from.
        """
        if not job.fleet_id or not job.program_id:
            # Nothing is sent, so there is nothing for the breaker to learn
            return False

        breaker = self.breakers.get_breaker(job.ce_region)
        if breaker.is_open:
            raise RunnerRetryableError(f"Fleets cancels in region {job.ce_region} are paused by the circuit breaker")
        try:
            written = self.transitions.stop(job, origin=JobEventOrigin.SCHEDULER, context=context)
        except FleetAppearedError:
            # Code Engine answered, the row changed under us. Not a region failure.
            breaker.record_success()
            raise
        except RunnerRetryableError:
            breaker.record_failure()
            raise
        except InvalidJobTransitionException:
            # The cancel landed, so the region answered. What the row did next is not its business.
            breaker.record_success()
            raise
        breaker.record_success()
        _REFUSED_CANCEL_WARNED.discard(str(job.id))
        return written == Job.STOPPING


def first_cancel_refusal(job: Job) -> bool:
    """True the first time this job's cancel is refused.

    Both scheduler callers ask again every tick for as long as the job is active, so they report the
    first refusal and drop to debug after it.
    """
    if str(job.id) in _REFUSED_CANCEL_WARNED:
        return False
    if len(_REFUSED_CANCEL_WARNED) >= _REFUSED_CANCEL_LIMIT:
        _REFUSED_CANCEL_WARNED.clear()
    _REFUSED_CANCEL_WARNED.add(str(job.id))
    return True


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

    queued = Job.objects.filter(status=Job.QUEUED, gpu=gpu, runner=runner)
    blocked = BlockedCloudResource.blocked_jobs_filter() if runner == Program.FLEETS else None
    if blocked is not None:
        # Held in QUEUED, and never picked: a picked job would take a slot it cannot use
        queued = queued.exclude(blocked)

    author_date_pull = (
        queued.exclude(author__in=users_at_max_capacity).values("author").annotate(job_date=Min("created"))[:max_limit]
    )

    if len(author_date_pull) == 0:
        return []

    author_date_list = list(author_date_pull)
    if len(author_date_pull) >= slots:
        author_date_list = random.sample(author_date_list, k=slots)

    job_filter = Q()
    for entry in author_date_list:
        job_filter |= Q(author=entry["author"]) & Q(created=entry["job_date"])

    return Job.objects.filter(job_filter).with_scheduler_context()


def check_job_timeout(job: Job):
    """Check job timeout and update job status."""

    if job.status in Job.RUNNING_STATUSES:
        timeout = settings.PROGRAM_TIMEOUT
        latest_job_event = JobEvent.objects.filter(job=job).order_by("-created").first()
        # A job without events counts from its creation.
        reference_time = latest_job_event.created if latest_job_event else job.created
        endtime = reference_time + timedelta(hours=timeout)
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
