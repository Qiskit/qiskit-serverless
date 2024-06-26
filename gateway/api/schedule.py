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

from api.models import Job
from api.ray import create_ray_job, kill_ray_cluster
from api.utils import generate_cluster_name
from main import settings as config


User: Model = get_user_model()
logger = logging.getLogger("commands")


def execute_job(job: Job) -> Job:
    """Executes program.

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
        cluster_name = generate_cluster_name(job.author.username)
        span.set_attribute("job.clustername", cluster_name)

        # test out running ray job
        job_resource = create_ray_job(job, cluster_name)
        logger.info(f"Ray Job {job_resource} created!")
        job.compute_resource = job_resource

        span.set_attribute("job.status", job.status)
    return job


def get_jobs_to_schedule_fair_share(slots: int) -> List[Job]:
    """Returns jobs for execution based on fair share distribution of resources.

    Args:
        slots: max number of users to query

    Returns:
        list of jobs for execution
    """

    # maybe refactor this using big SQL query :thinking:

    running_jobs_per_user = (
        Job.objects.filter(status__in=Job.RUNNING_STATES)
        .values("author")
        .annotate(running_jobs_count=Count("id"))
    )

    users_at_max_capacity = [
        entry["author"]
        for entry in running_jobs_per_user
        if entry["running_jobs_count"] >= settings.LIMITS_JOBS_PER_USER
    ]

    max_limit = 100  # not to kill db in case we will have a lot of jobs
    author_date_pull = (
        Job.objects.filter(status=Job.QUEUED)
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


def check_job_timeout(job: Job, job_status):
    """Check job timeout and update job status."""

    timeout = config.PROGRAM_TIMEOUT
    if job.updated:
        endtime = job.updated + timedelta(days=timeout)
        now = datetime.now(tz=endtime.tzinfo)
    if job.updated and endtime < now:  # pylint: disable=possibly-used-before-assignment
        job_status = Job.STOPPED
        job.logs += f"{job.logs}.\nMaximum job runtime reached. Stopping the job."
        logger.warning(
            "Job [%s] reached maximum runtime [%s] days and stopped.",
            job.id,
            timeout,
        )
    return job_status


def handle_job_status_not_available(job: Job, job_status):
    """Process job status not available and update job"""

    if config.RAY_CLUSTER_NO_DELETE_ON_COMPLETE:
        logger.debug(
            "RAY_CLUSTER_NO_DELETE_ON_COMPLETE is enabled, "
            + "so cluster [%s] will not be removed",
            job.compute_resource.title,
        )
    else:
        kill_ray_cluster(job.compute_resource.title)
        job.compute_resource.delete()
        job.compute_resource = None
        job_status = Job.FAILED
        job.logs += f"{job.logs}\nSomething went wrong during updating job status."
    return job_status
