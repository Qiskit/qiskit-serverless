"""Ray cluster related functions."""

import json
import logging
import os
import shutil
import tarfile
import time
import uuid
from typing import Optional

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

from api.services.arguments_storage import ArgumentsStorage
from api.models import ComputeResource, Job, JobConfig, DEFAULT_PROGRAM_ENTRYPOINT
from api.services.file_storage import FileStorage, WorkingDir
from api.utils import (
    retry_function,
    decrypt_env_vars,
    generate_cluster_name,
)
from utils import sanitize_file_path
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
            # get program
            program = job.program

            # get artifact
            working_directory_for_upload = os.path.join(
                sanitize_file_path(str(settings.MEDIA_ROOT)),
                "tmp",
                str(uuid.uuid4()),
            )
            if program.image is not None:
                # load default artifact
                os.makedirs(working_directory_for_upload, exist_ok=True)
                default_entrypoint_template = get_template("main.tmpl")
                default_entrypoint_content = default_entrypoint_template.render(
                    {
                        "mount_path": settings.CUSTOM_IMAGE_PACKAGE_PATH,
                        "package_name": settings.CUSTOM_IMAGE_PACKAGE_NAME,
                    }
                )
                with open(
                    os.path.join(
                        working_directory_for_upload, DEFAULT_PROGRAM_ENTRYPOINT
                    ),
                    "w",
                    encoding="utf-8",
                ) as entrypoint_file:
                    entrypoint_file.write(default_entrypoint_content)
            elif bool(program.artifact):
                with tarfile.open(program.artifact.path) as file:
                    file.extractall(working_directory_for_upload)
            else:
                raise ResourceNotFoundError(
                    f"Program [{program.title}] has no image or artifact associated."
                )

            # upload arguments to working directory
            provider_name = None
            if job.program.provider is not None:
                provider_name = job.program.provider.name
            storage = ArgumentsStorage(
                job.author.username, program.title, provider_name
            )
            arguments = storage.get(job.id)
            arguments_file = os.path.join(
                working_directory_for_upload, "arguments.serverless"
            )

            # DEPRECATED: arguments is now saved in /:username/:jobid,
            # arguments.serverless is going to be deprecated
            with open(arguments_file, "w", encoding="utf-8") as f:
                if arguments:
                    logger.debug("uploading arguments for job [%s]", job.id)
                    f.write(arguments)
                else:
                    f.write("{}")

            # set tracing
            carrier: dict[str, str] = {}
            TraceContextTextMapPropagator().inject(carrier)
            env_w_span = json.loads(job.env_vars)
            try:
                env_w_span["OT_TRACEPARENT_ID_KEY"] = carrier["traceparent"]
            except KeyError:
                pass

            env = decrypt_env_vars(env_w_span)
            token = env["ENV_JOB_GATEWAY_TOKEN"]
            env["QISKIT_IBM_RUNTIME_CUSTOM_CLIENT_APP_HEADER"] = (
                "middleware_job_id/" + str(job.id) + "," + token + "/"
            )
            ray_job_id = retry_function(
                callback=lambda: self.client.submit_job(
                    entrypoint=f"python {program.entrypoint}",
                    runtime_env={
                        "working_dir": working_directory_for_upload,
                        "env_vars": env,
                    },
                ),
                num_retries=settings.RAY_SETUP_MAX_RETRIES,
                error_message=f"Ray job [{job.id}] submission failed.",
            )

            if os.path.exists(working_directory_for_upload):
                shutil.rmtree(working_directory_for_upload)
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


def _create_cluster_data(job: Job, cluster_name: str):
    user = job.author
    job_config = job.config

    job_config = job_config or JobConfig()

    # can we remove the job_config in the left operator?
    job_config.workers = job_config.workers or settings.RAY_CLUSTER_WORKER_REPLICAS
    job_config.min_workers = (
        job_config.min_workers or settings.RAY_CLUSTER_WORKER_MIN_REPLICAS
    )
    job_config.max_workers = (
        job_config.max_workers or settings.RAY_CLUSTER_WORKER_MAX_REPLICAS
    )
    job_config.auto_scaling = (
        job_config.auto_scaling or settings.RAY_CLUSTER_WORKER_AUTO_SCALING
    )

    # cpu job settings
    node_selector_label = settings.RAY_CLUSTER_CPU_NODE_SELECTOR_LABEL

    # if gpu job, use gpu nodes and resources
    gpu_request = 0
    if job.gpu:
        node_selector_label = settings.RAY_CLUSTER_GPU_NODE_SELECTOR_LABEL
        gpu_request = settings.LIMITS_GPU_PER_TASK

    # configure provider configuration if needed
    node_image = settings.RAY_NODE_IMAGE
    provider_name = None
    if job.program.provider is not None:
        node_image = job.program.image
        provider_name = job.program.provider.name

    user_file_storage = FileStorage(
        username=user.username,
        working_dir=WorkingDir.USER_STORAGE,
        function_title=job.program.title,
        provider_name=provider_name,
    )
    provider_file_storage = user_file_storage
    if job.program.provider is not None:
        provider_file_storage = FileStorage(
            username=user.username,
            working_dir=WorkingDir.PROVIDER_STORAGE,
            function_title=job.program.title,
            provider_name=provider_name,
        )

    cluster = get_template("rayclustertemplate.yaml")
    manifest = cluster.render(
        {
            "cluster_name": cluster_name,
            "user_data_folder": user_file_storage.sub_path,
            "provider_data_folder": provider_file_storage.sub_path,
            "node_image": node_image,
            "workers": job_config.workers,
            "min_workers": job_config.min_workers,
            "max_workers": job_config.max_workers,
            "auto_scaling": job_config.auto_scaling,
            "user": user.username,
            "node_selector_label": node_selector_label,
            "gpu_request": gpu_request,
        }
    )
    cluster_data = yaml.safe_load(manifest)
    return cluster_data


def _is_local_mode():
    local = settings.RAY_CLUSTER_MODE.get("local")
    ray_local_host = settings.RAY_CLUSTER_MODE.get("ray_local_host")
    return local and ray_local_host


def _create_local_compute_resource(job: Job) -> ComputeResource:
    compute_resource = ComputeResource.objects.filter(
        host=settings.RAY_CLUSTER_MODE.get("ray_local_host")
    ).first()
    if compute_resource is None:
        compute_resource = ComputeResource(
            host=settings.RAY_CLUSTER_MODE.get("ray_local_host"),
            title="Local compute resource",
            owner=job.author,
        )
        compute_resource.save()

    return compute_resource


def _create_k8s_cluster(
    job: Job, cluster_name: Optional[str] = None, cluster_data: Optional[str] = None
) -> ComputeResource:
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
    user = job.author

    namespace = settings.RAY_KUBERAY_NAMESPACE
    cluster_name = cluster_name or generate_cluster_name(user.username)
    cluster_data = cluster_data or _create_cluster_data(job, cluster_name)

    config.load_incluster_config()
    k8s_client = kubernetes_client.api_client.ApiClient()
    dyn_client = DynamicClient(k8s_client)
    raycluster_client = dyn_client.resources.get(api_version="v1", kind="RayCluster")
    response = raycluster_client.create(body=cluster_data, namespace=namespace)
    if response.metadata.name != cluster_name:
        logger.warning(
            "Something went wrong during cluster creation: %s", response.text
        )
        raise RuntimeError("Something went wrong during cluster creation")

    # wait for cluster to be up and running
    host, cluster_is_ready = _wait_for_cluster_ready(cluster_name)

    if not cluster_is_ready:
        raise RuntimeError("Something went wrong during cluster creation: Timeout")

    compute_resource = ComputeResource(
        owner=user, title=cluster_name, host=host, gpu=job.gpu
    )
    compute_resource.save()

    return compute_resource


def create_compute_resource(  # pylint: disable=too-many-branches,too-many-locals,too-many-statements
    job: Job,
    cluster_name: Optional[str] = None,
    cluster_data: Optional[str] = None,
) -> ComputeResource:
    """
    Creates compute resource.
    If it is localhost, it creates a local compute resource of ray.
    If not it creates a ray cluster.

    Args:
        user: user cluster belongs to
        cluster_name: optional cluster name.
            by default username+uuid will be used
        cluster_data: optional cluster data

    Returns:
        returns compute resource associated with ray cluster.
    """

    if _is_local_mode():
        return _create_local_compute_resource(job)

    return _create_k8s_cluster(
        job, cluster_name=cluster_name, cluster_data=cluster_data
    )


def _wait_for_cluster_ready(cluster_name: str):
    """Waits for cluster to became available."""
    url = f"http://{cluster_name}-head-svc:8265/"
    success = False
    attempts = 0
    # not sure but readiness_time is not readiness time here,
    # the request.get has 5 secs of timeout and 1 sec sleeping,
    # so if max_attempts is 10, we will wait for 60 secs at worst case.
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
    if _is_local_mode():
        return True

    success = False
    namespace = settings.RAY_KUBERAY_NAMESPACE

    config.load_incluster_config()
    k8s_client = kubernetes_client.api_client.ApiClient()
    dyn_client = DynamicClient(k8s_client)
    raycluster_client = dyn_client.resources.get(api_version="v1", kind="RayCluster")
    try:
        delete_response = raycluster_client.delete(
            name=cluster_name, namespace=namespace
        )
    except NotFoundError as resource_not_found:
        sanitized = repr(resource_not_found).replace("\n", "").replace("\r", "")
        logger.error(
            "Something went wrong during ray cluster deletion request: %s",
            sanitized,
        )
        return success

    if delete_response.status == "Success":
        success = True
    else:
        sanitized = delete_response.text.replace("\n", "").replace("\r", "")
        logger.error(
            "Something went wrong during ray cluster deletion request: %s",
            sanitized,
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
