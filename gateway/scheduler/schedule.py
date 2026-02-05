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

from api.models import Job, ComputeResource
from core.services.ray import submit_job, create_compute_resource, kill_ray_cluster
from api.utils import generate_cluster_name, create_gpujob_allowlist

User: Model = get_user_model()
logger = logging.getLogger("commands")


def _create_ray_cluster_compute_resource(job: Job, span) -> ComputeResource | None:
    cluster_name = generate_cluster_name(job.author.username)
    span.set_attribute("job.clustername", cluster_name)

    compute_resource: ComputeResource | None = None
    try:
        compute_resource = create_compute_resource(job, cluster_name=cluster_name)
    except Exception:  # pylint: disable=broad-exception-caught
        # if something went wrong
        #   try to kill resource if it was allocated
        logger.warning(
            "Compute resource [%s] was not created properly.\n"
            "Setting job [%s] status to [FAILED].",
            cluster_name,
            job,
        )
        kill_ray_cluster(cluster_name)
        job.status = Job.FAILED
        job.logs += "\nCompute resource was not created properly."
        span.set_attribute("job.status", job.status)

    return compute_resource


def configure_job_to_use_gpu(job: Job):
    """
    Configures the Job if its allowed to use
    GPU or not.

    Args:
        job (Job): Job instance

    Returns:
        Job: the instance with gpu parameter configured
    """

    gpujobs = create_gpujob_allowlist()
    if (
        job.program
        and job.program.provider
        and job.program.provider.name in gpujobs["gpu-functions"].keys()
    ):
        logger.debug("Job [%s] will be run on GPU nodes", job.id)
        job.gpu = True

    return job


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
        compute_resource = _create_ray_cluster_compute_resource(job, span)
        if not compute_resource:
            return job

        job.compute_resource = compute_resource

        try:
            job = submit_job(job)
            job.status = Job.PENDING
        except Exception as ex:  # pylint: disable=broad-exception-caught:
            logger.error(
                "Exception was caught during scheduling job on user [%s] resource.\n"
                "Resource [%s] was in DB records, but address is not reachable.\n"
                "Cleaning up db record and setting job [%s] to failed: %s",
                job.author,
                compute_resource.title,
                job.id,
                ex,
            )
            kill_ray_cluster(compute_resource.title)
            compute_resource.delete()
            job.status = Job.FAILED
            job.compute_resource = None
            job.logs += "\nCompute resource was not found."

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
        Job.objects.filter(status__in=Job.RUNNING_STATUSES)
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
            "RAY_CLUSTER_NO_DELETE_ON_COMPLETE is enabled, "
            + "so cluster [%s] will not be removed",
            job.compute_resource.title,
        )
    else:
        kill_ray_cluster(job.compute_resource.title)
        job.compute_resource.delete()
        job.compute_resource = None
        job_status = Job.FAILED
        job.logs += "\nSomething went wrong during updating job status."
    return job_status


def fail_job_insufficient_resources(job: Job):
    """Fail job if insufficient resources are available."""
    if settings.RAY_CLUSTER_NO_DELETE_ON_COMPLETE:
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
    job.logs = (
        "Insufficient resources available to the run job in this "
        "configuration.\nMax resources allowed are "
        f"{settings.LIMITS_CPU_PER_TASK} CPUs and "
        f"{settings.LIMITS_MEMORY_PER_TASK} GB of RAM per job."
    )

    return job_status
