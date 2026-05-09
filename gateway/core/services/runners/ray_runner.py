"""Ray client for executing jobs on Ray clusters."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tarfile
import time
import uuid

import requests
import yaml
from django.conf import settings
from django.template.loader import get_template
from kubernetes import client as kubernetes_client, config
from kubernetes.dynamic.client import DynamicClient
from kubernetes.dynamic.exceptions import ResourceNotFoundError, NotFoundError
from ray.dashboard.modules.job.common import JobStatus
from ray.dashboard.modules.job.sdk import JobSubmissionClient

from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from core.models import ComputeResource, Job, JobConfig, DEFAULT_PROGRAM_ENTRYPOINT
from core.services.runners.abstract_runner import AbstractRunner, RunnerError
from core.services.storage.file_storage import FileStorage, WorkingDir
from core.utils import retry_function, decrypt_env_vars, sanitize_file_path

logger = logging.getLogger("RayRunner")


class RayRunner(AbstractRunner):
    """Client for executing jobs on Ray/KubeRay clusters."""

    def __init__(self, job: Job):
        """
        Initialize Ray client with a job.

        Args:
            job: Job instance to be executed
        """
        super().__init__(job)
        self._client: JobSubmissionClient | None = None

    def connect(self) -> None:
        """
        Connect to the Ray cluster via JobSubmissionClient.

        Raises:
            RunnerError: If unable to connect to Ray cluster
        """
        if self._connected:
            return

        self._client = self._create_client()
        self._connected = True

    def disconnect(self) -> None:
        """Close connection to Ray cluster."""
        self._client = None
        self._connected = False

    def is_active(self) -> bool:
        """Check if the Ray cluster host is alive and reachable.
        True if the Ray dashboard responds, False otherwise.
        """
        if not self._job or not self._job.compute_resource or not self._job.compute_resource.active:
            return False

        try:
            self._create_client()  # the client ray pings the server when it's created
            return True
        except Exception:  # pylint: disable=broad-exception-caught
            return False

    def _create_client(self):
        if not self._job:
            raise RunnerError("Unable to connect to Ray cluster at. No job linked to the client")

        compute_resource = self._job.compute_resource
        if not compute_resource:
            raise RunnerError("Unable to connect to Ray cluster at. No compute resource")
        host = compute_resource.host
        try:
            client = retry_function(
                callback=lambda: JobSubmissionClient(host),
                num_retries=settings.RAY_SETUP_MAX_RETRIES,
                error_message=f"Ray JobClientSubmission setup failed for host [{host}].",
            )
            logger.info(
                "[connect] job_id=%s cluster=%s host=%s Connected to Ray cluster",
                self._job.id,
                compute_resource,
                host,
            )
            return client
        except Exception as ex:
            logger.error(
                "[connect] job_id=%s cluster=%s host=%s error=%s Unable to connect to Ray cluster",
                self._job.id,
                compute_resource,
                host,
                ex,
            )
            raise RunnerError(f"Unable to connect to Ray cluster at [{host}]", ex) from ex

    def submit(self) -> None:
        """
        Submit the job to the Ray cluster.

        Creates the compute resource (K8s cluster or local) and submits the job.
        On failure, cleans up any created resources.

        Raises:
            RunnerError: If submission fails (resources are cleaned up before raising)
        """
        tracer = trace.get_tracer("scheduler.tracer")
        with tracer.start_as_current_span("submit.job") as span:
            # 1. Create compute resource
            cluster_name = None
            try:
                if settings.RAY_CLUSTER_MODE_LOCAL:
                    host = settings.RAY_LOCAL_HOST
                    title = "Local compute resource"
                else:
                    host, title = self._create_k8s_cluster()
                    cluster_name = title
                span.set_attribute("job.clustername", title)

                compute_resource = ComputeResource(
                    title=title,
                    host=host,
                    owner=self._job.author,
                    gpu=self._job.gpu,
                    active=True,
                )
                compute_resource.save()

                ray_job_id = self._submit_to_ray(compute_resource)

                self._job.ray_job_id = ray_job_id
                self._job.compute_resource = compute_resource
                self._job.status = Job.PENDING
                self._job.save(update_fields=["compute_resource", "ray_job_id", "status"])

                span.set_attribute("job.id", self._job.id)
                span.set_attribute("job.rayjobid", ray_job_id)
                logger.info(
                    "[submit] job_id=%s ray_job_id=%s cluster=%s Job submitted ok",
                    self._job.id,
                    ray_job_id,
                    title,
                )

            except Exception as ex:
                logger.error(
                    "[submit] job_id=%s cluster=%s error=%s Job submit failed",
                    self._job.id,
                    cluster_name,
                    ex,
                )
                if cluster_name:
                    if not _kill_ray_cluster(cluster_name, self._job.id):
                        logger.error(
                            "[submit] job_id=%s cluster=%s ORPHAN CLUSTER: "
                            "failed to delete cluster when job submit failed",
                            self._job.id,
                            cluster_name,
                        )

                raise RunnerError(f"Failed to submit job [{self._job.id}]", ex) from ex

    def status(self) -> str | None:
        """
        Get job status mapped to Job.STATUS.

        Returns:
            Job status string or None

        Raises:
            RunnerError: If unable to get job status
        """
        self._ensure_connected()

        try:
            ray_job_status = retry_function(
                callback=lambda: self._client.get_job_status(self._job.ray_job_id),
                error_message=f"Runtime error during status fetching from ray job [{self._job.ray_job_id}]",
            )
        except RuntimeError as ex:
            logger.error(
                "[status] job_id=%s ray_job_id=%s cluster=%s error=%s Job status failed",
                self._job.id,
                self._job.ray_job_id,
                self._job.compute_resource,
                ex,
            )
            raise RunnerError(f"Unable to get status for job [{self._job.ray_job_id}]", ex) from ex

        if ray_job_status is None:
            logger.warning(
                "[status] job_id=%s ray_job_id=%s cluster=%s Ray returned None status",
                self._job.id,
                self._job.ray_job_id,
                self._job.compute_resource,
            )
            return None

        status = _map_status(ray_job_status)
        logger.info(
            "[status] job_id=%s ray_job_id=%s cluster=%s Ray returned %s status (%s)",
            self._job.id,
            self._job.ray_job_id,
            self._job.compute_resource,
            ray_job_status,
            status,
        )
        return status

    def logs(self) -> str | None:
        """
        Get job logs.

        Returns:
            Job logs or None

        Raises:
            RunnerError: If unable to get job logs
        """
        self._ensure_connected()

        try:
            return retry_function(
                callback=lambda: self._client.get_job_logs(self._job.ray_job_id),
                error_message=f"Runtime error during logs fetching from ray job [{self._job.ray_job_id}]",
            )
        except RuntimeError as ex:
            logger.error(
                "[logs] job_id=%s ray_job_id=%s error=%s Get logs failed",
                self._job.id,
                self._job.ray_job_id,
                ex,
            )
            raise RunnerError(f"Unable to get logs for job [{self._job.ray_job_id}]", ex) from ex

    def provider_logs(self) -> str | None:
        """Return provider logs for this job.

        Ray has no distinction between user and provider logs, so this
        delegates to ``logs()``.

        Returns:
            Log content or ``None``.

        Raises:
            RunnerError: If unable to retrieve logs.
        """
        return self.logs()

    def stop(self) -> bool:
        """
        Stop the job.

        Returns:
            True if job was running and stopped

        Raises:
            RunnerError: If unable to stop the job
        """
        self._ensure_connected()

        try:
            return retry_function(
                callback=lambda: self._client.stop_job(self._job.ray_job_id),
                error_message=f"Runtime error during stopping of ray job [{self._job.ray_job_id}]",
            )
        except RuntimeError as ex:
            logger.error(
                "[stop] job_id=%s ray_job_id=%s error=%s Stop failed",
                self._job.id,
                self._job.ray_job_id,
                ex,
            )
            raise RunnerError(f"Unable to stop job [{self._job.ray_job_id}]", ex) from ex

    def free_resources(self) -> bool:
        """
        Clean up/delete the Ray cluster associated with the job.

        Returns:
            True if cleaned up correctly
        """
        if not self._job.compute_resource:
            logger.warning(
                "[free_resources] job_id=%s No compute_resource to free",
                self._job.id,
            )
            return False

        cluster = self._job.compute_resource.title
        logger.info(
            "[free_resources] job_id=%s cluster=%s Freeing cluster",
            self._job.id,
            cluster,
        )
        success = _kill_ray_cluster(cluster, self._job.id)
        if not success:
            logger.error(
                "[free_resources] job_id=%s cluster=%s Failed to free cluster",
                self._job.id,
                cluster,
            )
        return success

    def _submit_to_ray(self, compute_resource: ComputeResource) -> str:
        """
        Submit job to Ray cluster (internal method).

        Args:
            compute_resource: The compute resource to submit to

        Returns:
            ray job id
        """
        # get program
        program = self._job.program

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
                os.path.join(working_directory_for_upload, DEFAULT_PROGRAM_ENTRYPOINT),
                "w",
                encoding="utf-8",
            ) as entrypoint_file:
                entrypoint_file.write(default_entrypoint_content)
        elif bool(program.artifact):
            with tarfile.open(program.artifact.path) as file:
                file.extractall(working_directory_for_upload, filter="data")
        else:
            logger.error(
                "[_submit_to_ray] job_id=%s program=%s provider=%s No image or artifact associated",
                self._job.id,
                program.title,
                program.provider,
            )
            raise ResourceNotFoundError(f"Program [{program.title}] has no image or artifact associated.")

        # set tracing
        carrier: dict[str, str] = {}
        TraceContextTextMapPropagator().inject(carrier)
        env_w_span = json.loads(self._job.env_vars)
        try:
            env_w_span["OT_TRACEPARENT_ID_KEY"] = carrier["traceparent"]
        except KeyError:
            pass

        env = decrypt_env_vars(env_w_span)
        token = env["ENV_JOB_GATEWAY_TOKEN"]
        env["QISKIT_IBM_RUNTIME_CUSTOM_CLIENT_APP_HEADER"] = (
            "middleware_job_id/" + str(self._job.id) + "," + token + "/"
        )

        # Connect to Ray cluster using compute_resource host
        host = compute_resource.host
        logger.info(
            "[_submit_to_ray] job_id=%s cluster=%s host=%s Connecting to Ray cluster",
            self._job.id,
            compute_resource.title,
            host,
        )
        job_submission_client = retry_function(
            callback=lambda: JobSubmissionClient(host),
            num_retries=settings.RAY_SETUP_MAX_RETRIES,
            error_message=f"Ray JobClientSubmission setup failed for host [{host}].",
        )

        ray_job_id = retry_function(
            callback=lambda: job_submission_client.submit_job(
                entrypoint=f"python {program.entrypoint}",
                runtime_env={
                    "working_dir": working_directory_for_upload,
                    "env_vars": env,
                },
            ),
            num_retries=settings.RAY_SETUP_MAX_RETRIES,
            error_message=f"Ray job [{self._job.id}] submission failed.",
        )
        logger.info(
            "[_submit_to_ray] job_id=%s cluster=%s host=%s ray_job_id=%s Job submitted to Ray",
            self._job.id,
            compute_resource.title,
            host,
            ray_job_id,
        )

        if os.path.exists(working_directory_for_upload):
            shutil.rmtree(working_directory_for_upload)

        return ray_job_id

    def _create_k8s_cluster(self) -> tuple[str, str]:
        """
        Create Ray cluster on Kubernetes.

        Returns:
            Tuple of (host, cluster_name) for compute resource creation

        Raises:
            RuntimeError: If cluster creation fails
        """
        namespace = settings.RAY_KUBERAY_NAMESPACE
        cluster_name = _generate_resource_name(self._job.author.username)
        cluster_data = _create_cluster_data(cluster_name, self._job)

        config.load_incluster_config()
        k8s_client = kubernetes_client.api_client.ApiClient()
        dyn_client = DynamicClient(k8s_client)
        raycluster_client = dyn_client.resources.get(api_version="v1", kind="RayCluster")
        response = raycluster_client.create(body=cluster_data, namespace=namespace)
        created_cluster_name = response.metadata.name

        try:
            if created_cluster_name != cluster_name:
                logger.error(
                    "[_create_k8s_cluster] job_id=%s cluster=%s created_cluster=%s Cluster name mismatch",
                    self._job.id,
                    cluster_name,
                    created_cluster_name,
                )
                raise RuntimeError(f"Wrong name after cluster creation: {response.text}")

            host, cluster_is_ready = _wait_for_cluster_ready(cluster_name, str(self._job.id))
            if not cluster_is_ready:
                logger.error(
                    "[_create_k8s_cluster] job_id=%s cluster=%s Cluster creation timed out",
                    self._job.id,
                    cluster_name,
                )
                raise RuntimeError("Something went wrong during cluster creation: Timeout")
            logger.info(
                "[_create_k8s_cluster] job_id=%s cluster=%s host=%s Cluster ready",
                self._job.id,
                cluster_name,
                host,
            )
        except Exception:
            if not _kill_ray_cluster(created_cluster_name, self._job.id):
                logger.error(
                    "[_create_k8s_cluster] job_id=%s cluster=%s ORPHAN CLUSTER: failed to delete timed-out cluster",
                    self._job.id,
                    created_cluster_name,
                )
            raise

        return host, cluster_name


def _create_cluster_data(cluster_name: str, job: Job):
    """Create cluster configuration data."""
    user = job.author
    job_config = job.config

    job_config = job_config or JobConfig()

    job_config.workers = job_config.workers or settings.RAY_CLUSTER_WORKER_REPLICAS
    job_config.min_workers = job_config.min_workers or settings.RAY_CLUSTER_WORKER_MIN_REPLICAS
    job_config.max_workers = job_config.max_workers or settings.RAY_CLUSTER_WORKER_MAX_REPLICAS
    job_config.auto_scaling = job_config.auto_scaling or settings.RAY_CLUSTER_WORKER_AUTO_SCALING

    # cpu job settings
    node_selector_label = settings.RAY_CLUSTER_CPU_NODE_SELECTOR_LABEL

    # if gpu job, use gpu nodes and resources
    gpu_request = 0
    if job.gpu:
        node_selector_label = settings.RAY_CLUSTER_GPU_NODE_SELECTOR_LABEL
        gpu_request = settings.LIMITS_GPU_PER_TASK

    # configure provider configuration if needed
    node_image = settings.RAY_NODE_IMAGE
    if job.program.provider is not None:
        node_image = job.program.image

    user_file_storage = FileStorage(
        username=user.username,
        working_dir=WorkingDir.USER_STORAGE,
        function=job.program,
    )
    provider_file_storage = user_file_storage
    if job.program.provider is not None:
        provider_file_storage = FileStorage(
            username=user.username,
            working_dir=WorkingDir.PROVIDER_STORAGE,
            function=job.program,
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


def _wait_for_cluster_ready(cluster_name: str, job_id: str) -> tuple[str, bool]:
    """Wait for cluster to become available."""
    url = f"http://{cluster_name}-head-svc:8265/"
    max_time = settings.RAY_CLUSTER_MAX_READINESS_TIME
    start_time = time.time()
    while time.time() - start_time < max_time:
        try:
            response = requests.get(url, timeout=5)
            if response.ok:
                logger.info(
                    "[_wait_for_cluster_ready] job_id=%s cluster=%s elapsed=%.1fs Cluster ready",
                    job_id,
                    cluster_name,
                    time.time() - start_time,
                )
                return url, True

        except Exception as ex:  # pylint: disable=broad-exception-caught
            logger.debug(
                "[_wait_for_cluster_ready] job_id=%s cluster=%s Head node not ready yet: %s",
                job_id,
                cluster_name,
                str(ex),
            )
        time.sleep(0.5)

    elapsed = time.time() - start_time
    logger.warning(
        "[_wait_for_cluster_ready] job_id=%s cluster=%s elapsed=%.1fs Cluster not ready after %s timeout",
        job_id,
        cluster_name,
        elapsed,
        max_time,
    )
    return url, False


def _generate_resource_name(username: str) -> str:
    """Generate unique cluster name based on username."""
    lowercase_username = username.lower()[:20]
    pattern = re.compile("[^a-z0-9-]")
    return f"c-{re.sub(pattern, '-', lowercase_username)}-{str(uuid.uuid4())[:8]}"


def _map_status(ray_job_status) -> str:
    """
    Map Ray job status to Job model status.

    Args:
        ray_job_status: Ray JobStatus enum value

    Returns:
        Job status string
    """
    mapping = {
        JobStatus.PENDING: Job.PENDING,
        JobStatus.RUNNING: Job.RUNNING,
        JobStatus.STOPPED: Job.STOPPED,
        JobStatus.SUCCEEDED: Job.SUCCEEDED,
        JobStatus.FAILED: Job.FAILED,
    }
    return mapping.get(ray_job_status, Job.FAILED)


def _kill_ray_cluster(cluster_name: str, job_id=None) -> bool:
    """
    Kill Ray cluster by calling kuberay API.

    Args:
        cluster_name: Cluster name
        job_id: Optional job id for log context

    Returns:
        True if cluster was killed successfully
    """
    if settings.RAY_CLUSTER_MODE_LOCAL:
        return True

    start_time = time.time()
    namespace = settings.RAY_KUBERAY_NAMESPACE

    config.load_incluster_config()
    k8s_client = kubernetes_client.api_client.ApiClient()
    dyn_client = DynamicClient(k8s_client)
    raycluster_client = dyn_client.resources.get(api_version="v1", kind="RayCluster")
    try:
        delete_response = raycluster_client.delete(name=cluster_name, namespace=namespace)
    except NotFoundError as resource_not_found:
        sanitized = repr(resource_not_found).replace("\n", "").replace("\r", "")
        logger.warning(
            "[_kill_ray_cluster] [ANOMALY] job_id=%s cluster=%s elapsed=%.1fs "
            + "RayCluster NotFoundError when deleting (return true): %s",
            job_id,
            cluster_name,
            time.time() - start_time,
            sanitized,
        )
        # Returns true because the intention of killing the cluster was achieved
        return True
    except Exception as ex:  # pylint: disable=broad-exception-caught
        logger.error(
            "[_kill_ray_cluster] job_id=%s cluster=%s elapsed=%.1fs RayCluster deletion failed: %s. Return false",
            job_id,
            cluster_name,
            time.time() - start_time,
            str(ex),
        )
        return False

    success = delete_response.status == "Success"
    if success:
        logger.info(
            "[_kill_ray_cluster] job_id=%s cluster=%s RayCluster deletion success",
            job_id,
            cluster_name,
        )
    else:
        sanitized = delete_response.text.replace("\n", "").replace("\r", "")
        logger.error(
            "[_kill_ray_cluster] job_id=%s cluster=%s RayCluster deletion failed: %s",
            job_id,
            cluster_name,
            sanitized,
        )

    try:
        cert_client = dyn_client.resources.get(api_version="v1", kind="Certificate")
        try:
            cert_client.delete(name=cluster_name, namespace=namespace)
        except Exception as ex:  # pylint: disable=broad-exception-caught
            logger.warning(
                "[_kill_ray_cluster] job_id=%s cluster=%s Certificate deletion skipped: %s",
                job_id,
                cluster_name,
                ex,
            )
        try:
            cert_client.delete(name=f"{cluster_name}-worker", namespace=namespace)
        except Exception as ex:  # pylint: disable=broad-exception-caught
            logger.warning(
                "[_kill_ray_cluster] job_id=%s cluster=%s Certificate-worker deletion skipped: %s",
                job_id,
                cluster_name,
                ex,
            )
    except Exception as ex:  # pylint: disable=broad-exception-caught
        logger.warning(
            "[_kill_ray_cluster] job_id=%s cluster=%s Certificate client unavailable, skipping cert deletion: %s",
            job_id,
            cluster_name,
            ex,
        )

    try:
        corev1 = kubernetes_client.CoreV1Api()
        try:
            corev1.delete_namespaced_secret(name=cluster_name, namespace=namespace)
        except Exception as ex:  # pylint: disable=broad-exception-caught
            logger.warning(
                "[_kill_ray_cluster] job_id=%s cluster=%s Secret deletion skipped: %s",
                job_id,
                cluster_name,
                ex,
            )
        try:
            corev1.delete_namespaced_secret(name=f"{cluster_name}-worker", namespace=namespace)
        except Exception as ex:  # pylint: disable=broad-exception-caught
            logger.warning(
                "[_kill_ray_cluster] job_id=%s cluster=%s Secret-worker deletion skipped: %s",
                job_id,
                cluster_name,
                ex,
            )
    except Exception as ex:  # pylint: disable=broad-exception-caught
        logger.warning(
            "[_kill_ray_cluster] job_id=%s cluster=%s CoreV1Api unavailable, skipping secret deletion: %s",
            job_id,
            cluster_name,
            ex,
        )
    logger.info(
        "[_kill_ray_cluster] job_id=%s cluster=%s elapsed=%.1fs completed",
        job_id,
        cluster_name,
        time.time() - start_time,
    )
    return success
