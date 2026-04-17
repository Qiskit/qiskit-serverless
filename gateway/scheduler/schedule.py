"""Scheduling related functions."""

import logging
import random
from typing import List
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Model
from django.db.models import Q
from django.db.models.aggregates import Count, Min

from opentelemetry import trace

from core.models import Job
from core.services.runners import get_runner, RunnerError

User: Model = get_user_model()
logger = logging.getLogger("scheduler.schedule")


def execute_job(job: Job) -> Job:
    """Executes program.

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
            span.set_attribute("job.clustername", job.compute_resource.title)
        except RunnerError as ex:
            logger.error("job_id=%s error=%s Job set as FAILED: compute resource or submission error", job.id, ex)
            job.status = Job.FAILED
            job.logs += "\nCompute resource creation or job submission failed."

        span.set_attribute("job.status", job.status)
    return job


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


def check_job_timeout(job: Job):
    """Check job timeout and update job status."""

    timeout = settings.PROGRAM_TIMEOUT
    endtime = job.created + timedelta(days=timeout)
    now = datetime.now(tz=endtime.tzinfo)
    if endtime < now:
        job.logs += "\nMaximum job runtime reached. Stopping the job."
        logger.warning(
            "job_id=%s timeout_days=%s Job reached maximum runtime, stopping",
            job.id,
            timeout,
        )
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
