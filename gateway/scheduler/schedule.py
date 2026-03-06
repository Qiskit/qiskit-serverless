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

from core.models import Job, ComputeResource
from core.services.runners import get_runner_client, RunnerError

User: Model = get_user_model()
logger = logging.getLogger("commands")


def _create_ray_cluster_compute_resource(job: Job, runner, span) -> ComputeResource | None:
    compute_resource: ComputeResource | None = None
    try:
        compute_resource = runner.create_compute_resource()
        span.set_attribute("job.clustername", compute_resource.title)
    except RunnerError:
        # if something went wrong
        #   try to kill resource if it was allocated
        logger.warning(
            "Compute resource was not created properly.\nSetting job [%s] status to [FAILED].",
            job,
        )
        try:
            runner.free_resources()
        except RunnerError:
            pass
        job.status = Job.FAILED
        job.logs += "\nCompute resource was not created properly."
        span.set_attribute("job.status", job.status)

    return compute_resource


def execute_job(job: Job) -> Job:
    """Executes program.

    0. configure compute resource type
    1. check if cluster exists
       1.1 if not: create cluster
    2. connect to cluster
    3. run a job
    4. set status to pending

    Args:
        job: job to execute

    Returns:
        job of program execution
    """

    tracer = trace.get_tracer("scheduler.tracer")
    with tracer.start_as_current_span("execute.job") as span:
        runner = get_runner_client(job)
        compute_resource = _create_ray_cluster_compute_resource(job, runner, span)
        if not compute_resource:
            return job

        compute_resource.save()
        job.compute_resource = compute_resource

        try:
            ray_job_id = runner.submit()
            job.ray_job_id = ray_job_id
            job.status = Job.PENDING
        except RunnerError:
            logger.error(
                "Exception was caught during scheduling job on user [%s] resource.\n"
                "Resource [%s] was in DB records, but address is not reachable.\n"
                "Cleaning up db record and setting job [%s] to failed",
                job.author,
                compute_resource.title,
                job.id,
            )
            try:
                runner.free_resources()
            except RunnerError:
                pass
            compute_resource.delete()
            job.status = Job.FAILED
            job.compute_resource = None
            job.logs += "\nCompute resource was not found."

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
            "Job [%s] reached maximum runtime [%s] days and stopped.",
            job.id,
            timeout,
        )
        return True
    return False


def handle_job_status_not_available(job: Job, job_status):
    """Process job status not available and update job"""

    if settings.RAY_CLUSTER_NO_DELETE_ON_COMPLETE:
        logger.debug(
            "RAY_CLUSTER_NO_DELETE_ON_COMPLETE is enabled, so cluster [%s] will not be removed",
            job.compute_resource.title,
        )
    else:
        runner = get_runner_client(job)
        try:
            runner.free_resources()
        except RunnerError:
            pass
        job.compute_resource.delete()
        job.compute_resource = None
        job_status = Job.FAILED
        job.logs += "\nSomething went wrong during updating job status."
    return job_status


def fail_job_insufficient_resources(job: Job):
    """Fail job if insufficient resources are available."""
    if settings.RAY_CLUSTER_NO_DELETE_ON_COMPLETE:
        logger.debug(
            "RAY_CLUSTER_NO_DELETE_ON_COMPLETE is enabled, so cluster [%s] will not be removed",
            job.compute_resource.title,
        )
    else:
        runner = get_runner_client(job)
        try:
            runner.free_resources()
        except RunnerError:
            pass
        job.compute_resource.delete()
        job.compute_resource = None

    return Job.FAILED
