"""Schedule queued jobs service."""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List

from django.conf import settings
from django.db import DatabaseError, transaction
from django.db.models import Q, Min, Count

from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from core.config_key import ConfigKey
from core.models import ComputeResource, Job, JobEvent, Config
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from core.services.runners import RunnerError, get_runner, AbstractRunner

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from .task import SchedulerTask

logger = logging.getLogger("commands")


@dataclass
class JobExecutionResult:
    """Result of executing a job."""

    runner: AbstractRunner | None
    compute_resource: ComputeResource | None
    ray_job_id: str | None


class ScheduleQueuedJobs(SchedulerTask):
    """Schedule jobs service."""

    def __init__(self, kill_signal: KillSignal = None, metrics: SchedulerMetrics = None):
        self.kill_signal = kill_signal or KillSignal()
        self.metrics = metrics or SchedulerMetrics()

    def run(self):
        """Schedule queued jobs to available cluster slots."""
        if Config.get_bool(ConfigKey.MAINTENANCE):
            logger.warning("System in maintenance mode. Skipping new jobs schedule.")
            return

        self._schedule_cpu_jobs()
        self._schedule_gpu_jobs()

    def _schedule_cpu_jobs(self):
        """Schedule CPU jobs."""
        max_clusters = settings.LIMITS_MAX_CLUSTERS
        running_clusters = ComputeResource.objects.filter(active=True, gpu=False).count()
        self._schedule_jobs_if_slots_available(max_clusters, running_clusters, gpu_job=False)

    def _schedule_gpu_jobs(self):
        """Schedule GPU jobs."""
        max_clusters = settings.LIMITS_GPU_CLUSTERS
        running_clusters = ComputeResource.objects.filter(active=True, gpu=True).count()
        self._schedule_jobs_if_slots_available(max_clusters, running_clusters, gpu_job=True)

    def _schedule_jobs_if_slots_available(self, max_ray_clusters_possible, number_of_clusters_running, gpu_job):
        """Schedule jobs depending on free cluster slots."""
        free_clusters_slots = max_ray_clusters_possible - number_of_clusters_running

        # Store the queue size in the metrics
        self.set_queue_size_metric(gpu_job)

        if gpu_job:
            logger.info("%s free GPU cluster slots.", free_clusters_slots)
        else:
            logger.info("%s free CPU cluster slots.", free_clusters_slots)

        if free_clusters_slots < 1:
            # no available resources
            logger.info(
                "No clusters available. Resource consumption: %s / %s",
                number_of_clusters_running,
                max_ray_clusters_possible,
            )
            return

        jobs = get_jobs_to_schedule_fair_share(slots=free_clusters_slots, gpu=gpu_job)

        scheduled_count = 0
        for job in jobs:
            if self.kill_signal.received:
                return
            if schedule_job(job):
                scheduled_count += 1

        if scheduled_count > 0:
            logger.info("%s jobs scheduled for execution.", scheduled_count)

    def set_queue_size_metric(self, gpu_job):
        """Add queue size metric."""
        queue_count = Job.objects.filter(status=Job.QUEUED, gpu=gpu_job).count()
        compute_type = "gpu" if gpu_job else "cpu"
        self.metrics.set_queue_size(queue_count, compute_type)

    def add_queue_wait_time_metric(self, job: Job):
        """Add queue wait time metric."""
        # Wait time can be get from db -> wait_time = RUNNING event.timestamp - QUEUED event.timestamp
        # Jobs are created in QUEUED state, so "created" field should have the same timestamp as QUEUED event
        now = datetime.now(timezone.utc)
        wait_seconds = (now - job.created).total_seconds()
        job_compute_type = "gpu" if job.gpu else "cpu"
        self.metrics.observe_queue_wait_time(wait_seconds, job_compute_type)


def schedule_job(job: Job) -> bool:
    """Schedule a single job for execution.

    Args:
        job: Job to schedule

    Returns:
        True if job was scheduled successfully, False otherwise
    """
    env = json.loads(job.env_vars)
    ctx = TraceContextTextMapPropagator().extract(carrier=env)

    tracer = trace.get_tracer("scheduler.tracer")
    with tracer.start_as_current_span("scheduler.handle", context=ctx):

        execution_result = execute_job(job)

        if execution_result is None:
            _mark_job_as_failed(job)
            return False

        updated = _mark_job_as_running(job, execution_result)

        if not updated:
            logger.warning(
                "Job [%s]: Status changed while scheduling. Cleaning up resources.",
                job.id,
            )
            _cleanup_resources(job, execution_result)
            return False

        JobEvent.objects.add_status_event(
            job_id=job.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.SCHEDULE_JOBS,
            status=Job.RUNNING,
        )
        logger.info("Job [%s]: Scheduled for execution. Author: %s", job.id, job.author.id)
        return True


@transaction.atomic
def _mark_job_as_failed(job: Job):
    """Mark a job as failed when compute resource creation fails."""
    Job.objects.filter(id=job.id, status=Job.QUEUED).update(
        status=Job.FAILED,
    )
    JobEvent.objects.add_status_event(
        job_id=job.id,
        origin=JobEventOrigin.SCHEDULER,
        context=JobEventContext.SCHEDULE_JOBS,
        status=Job.FAILED,
    )
    logger.info("Job [%s]: Marked as FAILED.", job.id)


@transaction.atomic
def _mark_job_as_running(job: Job, result: JobExecutionResult) -> bool:
    """Save compute resource and update job status atomically.

    Returns:
        True if job was updated, False if job status changed while scheduling.
    """
    result.compute_resource.save()
    updated = Job.objects.filter(id=job.id, status=Job.QUEUED).update(
        status=Job.RUNNING,
        compute_resource=result.compute_resource,
        ray_job_id=result.ray_job_id,
    )
    return updated > 0


def _cleanup_resources(job: Job, result: JobExecutionResult):
    """Clean up resources when job status changed during scheduling."""
    try:
        result.runner.free_resources()
    except RunnerError as ex:
        logger.error("Job [%s]: Failed to free runner resources: %s", job.id, ex)

    try:
        result.compute_resource.delete()
    except (AttributeError, DatabaseError) as ex:
        logger.error("Job [%s]: Failed to delete compute resource: %s", job.id, ex)


def execute_job(job: Job) -> JobExecutionResult | None:
    """Executes program.

    1. Submit job to runner (which handles compute resource creation internally)
    2. Return result (or None on failure)

    Args:
        job: job to execute

    Returns:
        JobExecutionResult with compute_resource, ray_job_id, and runner
    """

    tracer = trace.get_tracer("scheduler.tracer")
    with tracer.start_as_current_span("execute.job") as span:
        runner = get_runner(job)

        try:
            compute_resource, runner_job_id = runner.submit()
            span.set_attribute("job.clustername", compute_resource.title)
            span.set_attribute("job.rayjobid", runner_job_id)
            return JobExecutionResult(
                compute_resource=compute_resource,
                ray_job_id=runner_job_id,
                runner=runner,
            )
        except RunnerError as ex:
            logger.error(
                "Job [%s]: Failed to submit job. Setting status to FAILED. Error: %s",
                job.id,
                ex,
            )
            span.set_attribute("job.status", Job.FAILED)
            return None


def get_jobs_to_schedule_fair_share(slots: int, gpu: bool) -> List[Job]:
    """Returns jobs for execution based on fair share distribution of resources.

    Args:
        slots: max number of users to query
        gpu: filter jobs by GPU requirement

    Returns:
        list of jobs for execution
    """

    # maybe refactor this using big SQL query :thinking:

    running_jobs_per_user = (
        Job.objects.filter(status__in=Job.RUNNING_STATUSES).values("author").annotate(running_jobs_count=Count("id"))
    )

    users_at_max_capacity = [
        entry["author"]
        for entry in running_jobs_per_user
        if entry["running_jobs_count"] >= settings.LIMITS_JOBS_PER_USER
    ]

    max_limit = 100  # not to kill db in case we will have a lot of jobs
    author_date_pull = (
        Job.objects.filter(status=Job.QUEUED, gpu=gpu)
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
