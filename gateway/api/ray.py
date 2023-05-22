"""Ray cluster related functions."""

import logging
import os
import shutil
import tarfile
import uuid
from typing import Any

import requests
from ray.dashboard.modules.job.sdk import JobSubmissionClient

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
            "env_vars": {
                # "ENV_JOB_GATEWAY_TOKEN": str(request.auth.token.decode()),  # TODO: get token
                "ENV_JOB_GATEWAY_HOST": str(settings.SITE_HOST),
                "ENV_JOB_ID_GATEWAY": str(job.id),
                "ENV_JOB_ARGUMENTS": program.arguments,
            },
            "pip": dependencies or [],
        },
    )
    job.ray_job_id = ray_job_id
    job.save()

    if os.path.exists(extract_folder):
        shutil.rmtree(extract_folder)

    return job


def create_compute_template_if_not_exists():
    """Creates default compute template for kuberay."""
    kube_ray_api_server_host = settings.RAY_KUBERAY_API_SERVER_URL
    namespace = settings.RAY_KUBERAY_NAMESPACE
    template_name = settings.RAY_KUBERAY_DEFAULT_TEMPLATE_NAME

    template_url = (
        f"{kube_ray_api_server_host}/apis/v1alpha2/"
        f"namespaces/{namespace}/compute_templates"
    )
    response = requests.get(f"{template_url}/{template_name}", timeout=30)
    if not response.ok:
        creation_response = requests.post(
            template_url,
            data={
                "name": template_name,
                "namespace": namespace,
                "cpu": 4,
                "memory": 4,
                "gpu": 0,
            },
            timeout=30,
        )

        if not creation_response.ok:
            raise RuntimeError("Cannot create compute template.")


def create_ray_cluster(user: Any) -> ComputeResource:
    """Creates ray cluster.

    1. check if compute template exists
        1.1 if not create compute tempalte
    2. create cluster

    Args:
        user: user cluster belongs to

    Returns:
        returns compute resource associated with ray cluster
    """
    kube_ray_api_server_host = settings.RAY_KUBERAY_API_SERVER_URL
    namespace = settings.RAY_KUBERAY_NAMESPACE
    image = settings.RAY_NODE_IMAGE
    template_name = settings.RAY_KUBERAY_DEFAULT_TEMPLATE_NAME

    clusters_url = (
        f"{kube_ray_api_server_host}/apis/v1alpha2/namespaces/{namespace}/clusters"
    )

    create_compute_template_if_not_exists()

    response = requests.post(
        clusters_url,
        data={
            "name": user.username,
            "namespace": namespace,
            "user": user.username,
            "version": "1.9.2",
            "environment": "DEV",
            "clusterSpec": {
                "headGroupSpec": {
                    "computeTemplate": "head-template",
                    "image": image,
                    "serviceType": "NodePort",
                    "rayStartParams": {},
                },
                "workerGroupSpec": [
                    {
                        "groupName": "default-worker-group",
                        "computeTemplate": template_name,
                        "image": image,
                        "replicas": 0,
                        "minReplicas": 0,
                        "maxReplicas": 4,
                        "rayStartParams": {},
                    }
                ],
            },
        },
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(
            f"Something went wrong during cluster creation: {response.text}"
        )

    # TODO: check for readiness

    resource = ComputeResource()
    resource.owner = user
    resource.title = user.username
    resource.host = ""  # TODO: fix name
    resource.save()
    return resource


def kill_ray_cluster(cluster_name: str) -> bool:
    """Kills ray cluster by calling kuberay api.

    Args:
        cluster_name: cluster name

    Returns:
        number of killed clusters
    """
    success = False
    kube_ray_api_server_host = settings.RAY_KUBERAY_API_SERVER_URL
    namespace = settings.RAY_KUBERAY_NAMESPACE
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
