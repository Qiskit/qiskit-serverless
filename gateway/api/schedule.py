"""Scheduling related functions."""
from typing import List

from api.models import Job, Program
from api.ray import submit_ray_job, create_ray_cluster


def save_program(serializer) -> Program:
    """Save program.

    Args:
        serializer: program serializer with data attached.

    Returns:
        saved program
    """
    raise NotImplementedError


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
    if job.compute_resource:
        job = submit_ray_job(job)
    else:
        compute_resource = create_ray_cluster(job.author.name)
        job.compute_resource = compute_resource
        job.save()
        job = submit_ray_job(job)

    return job


def get_jobs_to_schedule_fair_share(slots: int) -> List[Job]:
    """Returns jobs for execution based on fair share distribution of resources.

    Args:
        slots: max number of users to query

    Returns:
        list of jobs for execution
    """
    raise NotImplementedError
