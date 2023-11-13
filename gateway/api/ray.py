"""Ray cluster related functions."""
import json
import logging
import os
import shutil
import tarfile
import time
import uuid
from typing import Any, Optional

import requests
import yaml
from django.template.loader import get_template
from kubernetes import client as kubernetes_client, config
from kubernetes.client.exceptions import ApiException
from kubernetes.dynamic.client import DynamicClient
from kubernetes.dynamic.exceptions import ResourceNotFoundError, NotFoundError
from ray.dashboard.modules.job.sdk import JobSubmissionClient

from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from api.models import ComputeResource, Job, JobConfig
from api.utils import try_json_loads, retry_function, decrypt_env_vars
from main import settings

logger = logging.getLogger("commands")


class JobHandler:
    """JobHandler."""

    def __init__(self, client: JobSubmissionClient):
        """Job handler class.

        Args:
            client: ray job submission client.
        """
        self.client = client

    def status(self, ray_job_id) -> Optional[str]:
        """Get status of ray job."""
        return retry_function(
            callback=lambda: self.client.get_job_status(ray_job_id),
            error_message=f"Runtime error during status fetching from ray job [{ray_job_id}]",
        )

    def logs(self, ray_job_id: str) -> Optional[str]:
        """Get logs of ray job."""
        return retry_function(
            callback=lambda: self.client.get_job_logs(ray_job_id),
            error_message=f"Runtime error during logs fetching from ray job [{ray_job_id}]",
        )

    def stop(self, ray_job_id) -> bool:
        """Stop job."""
        return retry_function(
            callback=lambda: self.client.stop_job(ray_job_id),
            error_message=f"Runtime error during stopping of ray job [{ray_job_id}]",
        )

    def submit(self, job: Job) -> Optional[str]:
        """Submit job as ray job.

        Args:
            job: job

        Returns:
            ray job id
        """
        tracer = trace.get_tracer("scheduler.tracer")
        with tracer.start_as_current_span("submit.job") as span:
            program = job.program
            _, dependencies = try_json_loads(program.dependencies)
            with tarfile.open(program.artifact.path) as file:
                extract_folder = os.path.join(
                    settings.MEDIA_ROOT, "tmp", str(uuid.uuid4())
                )
                file.extractall(extract_folder)

            entrypoint = f"python {program.entrypoint}"
            carrier = {}
            TraceContextTextMapPropagator().inject(carrier)
            env_w_span = json.loads(job.env_vars)
            try:
                env_w_span["OT_TRACEPARENT_ID_KEY"] = carrier["traceparent"]
            except KeyError:
                pass

            ray_job_id = retry_function(
                callback=lambda: self.client.submit_job(
                    entrypoint=entrypoint,
                    runtime_env={
                        "working_dir": extract_folder,
                        "env_vars": decrypt_env_vars(env_w_span),
                        "pip": dependencies or [],
                    },
                ),
                num_retries=settings.RAY_SETUP_MAX_RETRIES,
                error_message=f"Ray job [{job.id}] submission failed.",
            )

            if os.path.exists(extract_folder):
                shutil.rmtree(extract_folder)
            span.set_attribute("job.rayjobid", job.ray_job_id)

        return ray_job_id


def get_job_handler(host: str) -> Optional[JobHandler]:
    """Establishes connection of job client with ray cluster.

    Args:
        host: host of ray cluster

    Returns:
        job client

    Raises:
        connection error exception
    """
    return retry_function(
        callback=lambda: JobHandler(JobSubmissionClient(host)),
        num_retries=settings.RAY_SETUP_MAX_RETRIES,
        error_message=f"Ray JobClientSubmission setup failed for host [{host}].",
    )


def submit_job(job: Job) -> Job:
    """Submits job to ray cluster.

    Args:
        job: gateway job to run as ray job

    Returns:
        submitted job
    """
    ray_client = get_job_handler(job.compute_resource.host)
    if ray_client is None:
        logger.error(
            "Unable to set up ray client with host [%s]", job.compute_resource.host
        )
        raise ConnectionError(
            f"Unable to set up ray client with host [{job.compute_resource.host}]"
        )

    ray_job_id = ray_client.submit(job)
    if ray_job_id is None:
        logger.error("Unable to submit ray job [%s]", job.id)
        raise ConnectionError(f"Unable to submit ray job [{job.id}]")

    # TODO: if submission failed log message and save with failed status to prevent loop over  # pylint: disable=fixme
    job.ray_job_id = ray_job_id
    job.status = Job.PENDING

    return job


def create_ray_cluster(
    user: Any,
    cluster_name: Optional[str] = None,
    cluster_data: Optional[str] = None,
    job_config: Optional[JobConfig] = None,
) -> Optional[ComputeResource]:
    """Creates ray cluster.

    Args:
        user: user cluster belongs to
        cluster_name: optional cluster name.
            by default username+uuid will be used
        cluster_data: optional cluster data

    Returns:
        returns compute resource associated with ray cluster
        or None if something went wrong with cluster creation.
    """
    namespace = settings.RAY_KUBERAY_NAMESPACE
    cluster_name = cluster_name or f"{user.username}-{str(uuid.uuid4())[:8]}"
    if not cluster_data:
        if not job_config:
            job_config = JobConfig()
        if not job_config.workers:
            job_config.workers = settings.RAY_CLUSTER_WORKER_REPLICAS
        if not job_config.min_workers:
            job_config.min_workers = settings.RAY_CLUSTER_WORKER_MIN_REPLICAS
        if not job_config.max_workers:
            job_config.max_workers = settings.RAY_CLUSTER_WORKER_MAX_REPLICAS
        if not job_config.auto_scaling:
            job_config.auto_scaling = settings.RAY_CLUSTER_WORKER_AUTO_SCALING

        cluster = get_template("rayclustertemplate.yaml")
        manifest = cluster.render(
            {
                "cluster_name": cluster_name,
                "user_id": user.username,
                "workers": job_config.workers,
                "min_workers": job_config.min_workers,
                "max_workers": job_config.max_workers,
                "auto_scaling": job_config.auto_scaling,
            }
        )
        cluster_data = yaml.safe_load(manifest)

    config.load_incluster_config()
    k8s_client = kubernetes_client.api_client.ApiClient()
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
                logger.debug("Head node %s is not ready yet.", url)
            time.sleep(1)
        else:
            logger.warning("Waiting too long for cluster [%s] creation", cluster_name)
            break
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
    k8s_client = kubernetes_client.api_client.ApiClient()
    dyn_client = DynamicClient(k8s_client)
    raycluster_client = dyn_client.resources.get(
        api_version="v1alpha1", kind="RayCluster"
    )
    try:
        delete_response = raycluster_client.delete(
            name=cluster_name, namespace=namespace
        )
    except NotFoundError as resource_not_found:
        logger.error(
            "Something went wrong during ray cluster deletion request: %s",
            resource_not_found,
        )
        return success

    if delete_response.status == "Success":
        success = True
    else:
        logger.error(
            "Something went wrong during ray cluster deletion request: %s",
            delete_response.text,
        )
    try:
        cert_client = dyn_client.resources.get(api_version="v1", kind="Certificate")
    except ResourceNotFoundError:
        return success

    try:
        cert_client.delete(name=cluster_name, namespace=namespace)
        success = True
    except NotFoundError:
        logger.error(
            "Something went wrong during ray certification deletion request: %s",
            cluster_name,
        )
    try:
        cert_client.delete(name=f"{cluster_name}-worker", namespace=namespace)
        success = True
    except NotFoundError:
        logger.error(
            "Something went wrong during ray certification deletion request: %s",
            f"{cluster_name}-worker",
        )

    corev1 = kubernetes_client.CoreV1Api()
    try:
        corev1.delete_namespaced_secret(name=cluster_name, namespace=namespace)
        success = True
    except ApiException:
        logger.error(
            "Something went wrong during ray secret deletion request: %s",
            cluster_name,
        )
    try:
        corev1.delete_namespaced_secret(
            name=f"{cluster_name}-worker", namespace=namespace
        )
        success = True
    except ApiException:
        logger.error(
            "Something went wrong during ray secret deletion request: %s",
            f"{cluster_name}-worker",
        )
    return success
