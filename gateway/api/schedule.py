"""Scheduling related functions."""
import logging
from typing import List

import requests

from api.models import Job, Program


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

    Args:
        job: job to execute

    Returns:
        job of program execution
    """
    # check if cluster exists
    #   if not: create cluster
    # connect to cluster
    # run a job
    # set status to pending
    raise NotImplementedError


def kill_ray_cluster(cluster_name: str) -> bool:
    """Kills ray cluster by calling kuberay api.

    Args:
        cluster_name: cluster name

    Returns:
        number of killed clusters
    """
    success = False
    kube_ray_api_server_host = ""
    namespace = ""
    url = f"{kube_ray_api_server_host}/apis/v1alpha2/namespaces/{namespace}/clusters/{cluster_name}"
    delete_response = requests.delete(url=url, timeout=30)
    if delete_response.ok:
        success = True
    else:
        logging.error(
            "Something went wrong during ray cluster deletion request: %s",
            delete_response.text,
        )
    return success


def get_jobs_to_schedule_fair_share(slots: int) -> List[Job]:
    """Returns jobs for execution based on fair share distribution of resources.

    Args:
        slots: max number of users to query

    Returns:
        list of jobs for execution
    """
    raise NotImplementedError
