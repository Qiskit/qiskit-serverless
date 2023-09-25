"""Scheduling related functions."""
import logging
import random
import uuid
from typing import List
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Model
from django.db.models import Q
from django.db.models.aggregates import Count, Min

from opentelemetry import trace

from api.models import Job, Program, ComputeResource
from api.ray import submit_job, create_ray_cluster, kill_ray_cluster
from main import settings as config

User: Model = get_user_model()
logger = logging.getLogger("commands")


def save_program(serializer, request) -> Program:
    """Save program.

    Args:
        serializer: program serializer with data attached.

    Returns:
        saved program
    """
    program = Program(**serializer.data)
    program.artifact = request.FILES.get("artifact")
    program.author = request.user
    program.save()
    return program


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
        authors_resource = ComputeResource.objects.filter(
            owner=job.author, active=True
        ).first()

        cluster_name = f"c-{job.author.username}-{str(uuid.uuid4())[:8]}"
        span.set_attribute("job.clustername", cluster_name)
        if authors_resource:
            try:
                job.compute_resource = authors_resource
                job = submit_job(job)
                job.status = Job.PENDING
            except (
                Exception  # pylint: disable=broad-exception-caught
            ) as missing_resource_exception:
                logger.error(
                    "Exception was caught during scheduling job on user [%s] resource.\n"
                    "Resource [%s] was in DB records, but address is not reachable.\n"
                    "Cleaning up db record and setting job [%s] to failed.\n"
                    "Error trace: %s",
                    job.author,
                    authors_resource.title,
                    job.id,
                    missing_resource_exception,
                )
                kill_ray_cluster(authors_resource.title)
                authors_resource.delete()
                job.status = Job.FAILED
                job.logs = "Compute resource was not found."
        else:
            compute_resource = create_ray_cluster(job.author, cluster_name=cluster_name)
            if compute_resource:
                # if compute resource was created in time with no problems
                job.compute_resource = compute_resource
                job = submit_job(job)
                job.status = Job.PENDING
            else:
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
                job.logs = "Compute resource was not created properly."
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
    if job.updated and endtime < now:
        job_status = Job.STOPPED
        job.logs = f"{job.logs}.\nMaximum job runtime reached. Stopping the job."
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
        job.logs = f"{job.logs}\nSomething went wrong during updating job status."
    return job_status
