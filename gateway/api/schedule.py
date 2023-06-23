"""Scheduling related functions."""
import random
from typing import List

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Model
from django.db.models import Q
from django.db.models.aggregates import Count, Min

from api.models import Job, Program, ComputeResource
from api.ray import submit_ray_job, create_ray_cluster, kill_ray_cluster

User: Model = get_user_model()


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
    authors_resource = ComputeResource.objects.filter(owner=job.author).first()

    if authors_resource:
        try:
            job.compute_resource = authors_resource
            job = submit_ray_job(job)
            job.status = Job.PENDING
            job.save()
        except Exception:
            authors_resource.delete()
            kill_ray_cluster(cluster_name)
            job.status = Job.FAILED
            job.logs = "Something went wrong during compute resource allocation."
            job.save()
    else:
        compute_resource = create_ray_cluster(job.author)
        if compute_resource:
            # if compute resource was created in time with no problems
            job.compute_resource = compute_resource
            job.save()
            job = submit_ray_job(job)
            job.status = Job.PENDING
            job.save()
        else:
            # if something went wrong
            #   try to kill resource if it was allocated
            kill_ray_cluster(job.author.username)
            job.status = Job.FAILED
            job.logs = "Something went wrong during compute resource allocation."
            job.save()
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
