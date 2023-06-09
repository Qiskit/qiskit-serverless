"""Ray cluster related functions."""
import json
import logging
import os
import shutil
import tarfile
import time
import uuid
from typing import Any, Optional

import yaml
from kubernetes import client, config
from kubernetes.dynamic.client import DynamicClient

import requests
from ray.dashboard.modules.job.sdk import JobSubmissionClient

from django.template.loader import get_template

from api.models import ComputeResource, Job
from api.utils import try_json_loads
from main import settings


def submit_ray_job(job: Job) -> Job:
    """Submits job to ray cluster.

    Args:
        job: gateway job to run as ray job

    Returns:
        submitted job
    """
    ray_client = JobSubmissionClient(job.compute_resource.host)
    program = job.program

    _, dependencies = try_json_loads(program.dependencies)
    with tarfile.open(program.artifact.path) as file:
        extract_folder = os.path.join(settings.MEDIA_ROOT, "tmp", str(uuid.uuid4()))
        file.extractall(extract_folder)

    entrypoint = f"python {program.entrypoint}"
    ray_job_id = ray_client.submit_job(
        entrypoint=entrypoint,
        runtime_env={
            "working_dir": extract_folder,
            "env_vars": json.loads(job.env_vars),
            "pip": dependencies or [],
        },
    )
    job.ray_job_id = ray_job_id
    job.status = Job.PENDING
    job.save()

    if os.path.exists(extract_folder):
        shutil.rmtree(extract_folder)

    return job


def create_ray_cluster(
    user: Any, cluster_name: Optional[str] = None
) -> Optional[ComputeResource]:
    """Creates ray cluster.

    Args:
        user: user cluster belongs to
        cluster_name: optional cluster name.
            by default username+uuid will be used

    Returns:
        returns compute resource associated with ray cluster
        or None if something went wrong with cluster creation.
    """
    namespace = settings.RAY_KUBERAY_NAMESPACE
    cluster_name = cluster_name or f"{user.username}-{str(uuid.uuid4())[:8]}"
    cluster = get_template("rayclustertemplate.yaml")
    cluster_data = yaml.safe_load(
        cluster.render(
            {"cluster_name": cluster_name}
        )
    )

    config.load_incluster_config()
    k8s_client = client.api_client.ApiClient()
    dyn_client = DynamicClient(k8s_client)
    raycluster_client = dyn_client.resources.get(
        api_version="v1alpha1", kind="RayCluster"
    )
    response = raycluster_client.create(body=cluster_data, namespace=namespace)
    if response.metadata.name != cluster_name:
        raise RuntimeError(
            f"Something went wrong during cluster creation: {response.text}"
        )

    # wait for cluster to be up and running
    host, cluster_is_ready = wait_for_cluster_ready(cluster_name)

    resource = None
    if cluster_is_ready:
        resource = ComputeResource()
        resource.owner = user
        resource.title = cluster_name
        resource.host = host
        resource.save()
    return resource


def wait_for_cluster_ready(cluster_name: str):
    """Waits for cluster to became available."""
    url = f"http://{cluster_name}-head-svc:8265/"
    success = False
    attempts = 0
    max_attempts = settings.RAY_CLUSTER_MAX_READINESS_TIME
    while not success:
        attempts += 1

        if attempts <= max_attempts:
            try:
                response = requests.get(url, timeout=5)
                if response.ok:
                    success = True
            except Exception:  # pylint: disable=broad-exception-caught
                logging.debug("Head node %s is not ready yet.", url)
            time.sleep(1)
        else:
            logging.warning("Waiting too long for cluster [%s] creation", cluster_name)
    return url, success


def kill_ray_cluster(cluster_name: str) -> bool:
    """Kills ray cluster by calling kuberay api.

    Args:
        cluster_name: cluster name

    Returns:
        number of killed clusters
    """
    success = False
    namespace = settings.RAY_KUBERAY_NAMESPACE

    config.load_incluster_config()
    k8s_client = client.api_client.ApiClient()
    dyn_client = DynamicClient(k8s_client)
    raycluster_client = dyn_client.resources.get(
        api_version="v1alpha1", kind="RayCluster"
    )
    delete_response = raycluster_client.delete(name=cluster_name, namespace=namespace)
    if delete_response.status == "Success":
        success = True
    else:
        logging.error(
            "Something went wrong during ray cluster deletion request: %s",
            delete_response.text,
        )
    return success
