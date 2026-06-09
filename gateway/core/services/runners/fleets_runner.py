# This code is part of a Qiskit project.
#
# (C) IBM 2026
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Runner for executing jobs on IBM Code Engine Fleets."""

from __future__ import annotations

import json
import logging
import re
import tarfile
import time
from collections import OrderedDict
from io import BytesIO

from django.conf import settings
from django.template.loader import get_template
from core.ibm_cloud.code_engine.ce_client.rest import ApiException

from core.models import Job, CodeEngineProject
from core.services.runners.abstract_runner import AbstractRunner, RunnerError
from core.ibm_cloud import get_ce_auth, get_cos_client
from core.utils import decrypt_env_vars
from core.ibm_cloud.code_engine.fleets.handler import FleetHandler
from core.ibm_cloud.code_engine.fleets.cos import JobCOS
from core.ibm_cloud.code_engine.fleets.utils import (
    FleetJobPaths,
    build_job_paths,
    build_run_env_variables,
    build_run_volume_mounts_for_job,
)

logger = logging.getLogger("FleetsRunner")


class TTLCache:
    """Fixed-size cache with per-entry TTL, evicting oldest entries when full."""

    def __init__(self, maxsize: int = 1000, ttl: float = 30) -> None:
        self._store: OrderedDict[str, tuple] = OrderedDict()
        self._maxsize = maxsize
        self._ttl = ttl

    def get(self, key: str):
        """Return cached value if present and not expired, else ``None``."""
        entry = self._store.get(key)
        if entry and (time.monotonic() - entry[1]) < self._ttl:
            return entry[0]
        self._store.pop(key, None)
        return None

    def put(self, key: str, value) -> None:
        """Store a value, evicting the oldest entry if the cache is full."""
        self._store.pop(key, None)
        if len(self._store) >= self._maxsize:
            self._store.popitem(last=False)
        self._store[key] = (value, time.monotonic())


def _retry_on_rate_limit(fn, retries=3, delays=(0.5, 1.0, 2.0)):
    """Call *fn* with retries on HTTP 429 (Too Many Requests).

    Args:
        fn: Zero-argument callable to execute.
        retries: Maximum number of retry attempts.
        delays: Sleep durations between attempts.

    Returns:
        The return value of *fn*.
    """
    for attempt in range(retries + 1):
        try:
            return fn()
        except ApiException as exc:
            if exc.status != 429 or attempt >= retries:
                raise
            delay = delays[min(attempt, len(delays) - 1)]
            logger.warning("Rate limited (429), retrying in %.1fs (attempt %d/%d)", delay, attempt + 1, retries)
            time.sleep(delay)
    return None


class FleetsRunner(AbstractRunner):
    """Runner that executes jobs on IBM Code Engine Fleets.

    Each runner instance is tied to a single :class:`~core.models.Job`. The
    underlying :class:`FleetHandler` is created lazily on first use and
    recreated automatically when the cached IAM token is rotated.
    """

    _is_active_cache = TTLCache(maxsize=1000, ttl=30)

    def __init__(self, job: Job) -> None:
        """Initialize the runner.

        Args:
            job: Job instance to execute.
        """
        super().__init__(job)
        self._handler: FleetHandler | None = None
        self._project: CodeEngineProject | None = None
        self._cos: JobCOS | None = None

    def connect(self) -> None:
        """Initialize the FleetHandler and validate IBM Cloud credentials.

        Raises:
            RunnerError: If the handler cannot be created.
        """
        if self._connected:
            return
        try:
            self._get_handler()
            self._connected = True
            logger.info("Connected to Code Engine Fleets in region [%s]", self._project.region)
        except Exception as ex:
            region = self._project.region if self._project else "unknown"
            raise RunnerError(f"Unable to connect to Code Engine Fleets in region [{region}]", ex) from ex

    def disconnect(self) -> None:
        """No-op — FleetHandler is a stateless REST client."""

    def is_active(self) -> bool:
        """Return ``True`` if the fleet exists in Code Engine.

        Results are cached for 30 seconds (class-level :class:`TTLCache`)
        to avoid redundant API calls when the scheduler polls frequently.

        Returns:
            ``True`` when the fleet is reachable, ``False`` otherwise.
        """
        if not self.job.fleet_id:
            return False

        cached = self._is_active_cache.get(self.job.fleet_id)
        if cached is not None:
            return cached

        try:
            self._ensure_connected()
            self._get_handler().get_job_status(self.job.fleet_id)
            self._is_active_cache.put(self.job.fleet_id, True)
            return True
        except ApiException as ex:
            if ex.status == 404:
                self._is_active_cache.put(self.job.fleet_id, False)
                return False
            logger.warning("CE API error checking fleet [%s]: status=%s", self.job.fleet_id, ex.status)
            return False
        except Exception:  # pylint: disable=broad-exception-caught
            logger.warning("Unable to verify fleet [%s] existence", self.job.fleet_id)
            return False

    def submit(self) -> None:
        """Submit the job as a Code Engine fleet.

        When COS is configured, mounts two PDS volumes and sets up the
        dual-log wrapper (provider log = all output, user log = ``[public]``
        filtered lines). Arguments and artifact files are uploaded to COS
        before the fleet is created.

        Raises:
            RunnerError: If submission fails.
        """
        try:
            handler = self._get_handler()

            timestamp = int(time.time())
            fleet_name = f"job-{self.job.id}-{timestamp}"

            logger.info(
                "Submitting job_id=[%s] as fleet [%s] to project [%s]",
                self.job.id,
                fleet_name,
                self._project.project_name,
            )

            extra_fields: dict = {}

            cpu_limit, memory_limit, scale_gpu = self._parse_compute_profile()
            logger.info(
                "job_id=[%s] profile [%s] → cpu=%s memory=%s gpu=%s",
                self.job.id,
                self.job.compute_profile or "default",
                cpu_limit,
                memory_limit,
                scale_gpu,
            )
            if scale_gpu:
                extra_fields["scale_gpu"] = scale_gpu

            if self._is_cos_configured():
                paths = build_job_paths(self.job)

                run_volume_mounts = build_run_volume_mounts_for_job(paths, self._project)
                stored_env_vars = json.loads(self.job.env_vars)
                stored_env_vars = decrypt_env_vars(stored_env_vars)
                run_env_variables = build_run_env_variables(paths, stored_env_vars)
                extra_fields.update(
                    {
                        "run_volume_mounts": run_volume_mounts,
                        "run_env_variables": run_env_variables,
                        "run_commands": ["python", paths.container_docker_entrypoint],
                    }
                )
                _retry_on_rate_limit(lambda: self._upload_program_to_cos(paths))
                logger.info(
                    "COS configured for job_id [%s]: user_key=[%s] provider_key=[%s]",
                    self.job.id,
                    paths.cos_user_log_key,
                    paths.cos_provider_log_key,
                )
            else:
                raise RunnerError(f"COS is not configured for job_id=[{self.job.id}] — cannot submit Fleets job")

            fleet = _retry_on_rate_limit(
                lambda: handler.submit_job(
                    name=fleet_name,
                    image_reference=self._get_image(),
                    image_secret=settings.CE_ICR_PULL_SECRET,
                    network_placements=[{"type": "subnet_pool", "reference": self._project.subnet_pool_id}],
                    scale_cpu_limit=cpu_limit,
                    scale_memory_limit=memory_limit,
                    scale_max_instances=self._get_max_instances(),
                    scale_retry_limit=0,
                    tasks_specification={"indices": "0"},
                    tasks_state_store={"persistent_data_store": self._project.pds_name_state},
                    extra_fields=extra_fields or None,
                )
            )

            fleet_dict = fleet.to_dict() if hasattr(fleet, "to_dict") else dict(fleet)
            fleet_id = fleet_dict.get("id")
            if not fleet_id:
                raise RunnerError("Fleet submission succeeded but no fleet ID returned")

            logger.info("Submitted job_id=[%s] as fleet [%s]", self.job.id, fleet_id)
            self.job.fleet_id = fleet_id

        except ApiException as ex:
            logger.error(
                "CE API error submitting job_id=[%s]: status=%s reason=%s",
                self.job.id,
                ex.status,
                ex.reason,
            )
            raise RunnerError(f"Code Engine API error: {ex.reason}", ex) from ex
        except RunnerError:
            raise
        except Exception as ex:
            logger.error("Failed to submit job_id=[%s]: %s", self.job.id, ex)
            raise RunnerError(f"Failed to submit job_id=[{self.job.id}] to Code Engine Fleets", ex) from ex

    def status(self) -> str | None:
        """Return the job status mapped to :attr:`Job.STATUS`.

        Returns ``None`` on a 429 rate-limit response so the scheduler keeps
        the job in its current state and retries on the next poll cycle.

        Returns:
            Mapped status string or ``None``.

        Raises:
            RunnerError: On non-recoverable API errors.
        """
        self._ensure_connected()
        if not self.job.fleet_id:
            raise RunnerError("Job has no fleet_id assigned")

        try:
            fleet_status = self._get_handler().get_job_status(self.job.fleet_id)
            raw = fleet_status.get("status")
            mapped = self._map_fleet_status(raw) if raw else None
            logger.debug("Fleet [%s] status: %s → %s", self.job.fleet_id, raw, mapped)
            if mapped in (Job.FAILED, Job.STOPPED):
                logger.warning("Fleet [%s] terminal status [%s] raw=[%s]", self.job.fleet_id, mapped, raw)
            return mapped

        except ApiException as ex:
            if ex.status == 429:
                logger.warning("Rate limit (429) for fleet [%s] — retrying next poll", self.job.fleet_id)
                return None
            logger.error(
                "CE API error getting status for fleet [%s]: status=%s reason=%s",
                self.job.fleet_id,
                ex.status,
                ex.reason,
            )
            raise RunnerError(f"Code Engine API error: {ex.reason}", ex) from ex
        except Exception as ex:
            logger.error("Failed to get status for fleet [%s]: %s", self.job.fleet_id, ex)
            raise RunnerError(f"Unable to get status for fleet [{self.job.fleet_id}]", ex) from ex

    def logs(self) -> str | None:
        """
        logs and provider_logs don't require implementation because we always go to the
        object storage directly to retrieve this information in fleets. So we use the logs
        storage to work with this data.
        """
        raise NotImplementedError

    def provider_logs(self) -> str | None:
        """
        logs and provider_logs don't require implementation because we always go to the
        object storage directly to retrieve this information in fleets. So we use the logs
        storage to work with this data.
        """
        raise NotImplementedError

    def get_result_from_cos(self) -> str | None:
        """Retrieve job results from COS.

        Results are written by the container at
        ``{user_job_prefix}/results.json``.

        Returns:
            JSON string or ``None`` if COS is not configured or the file is absent.
        """
        if not self._is_cos_configured():
            logger.debug("COS not configured for job_id=[%s]", self.job.id)
            return None

        try:
            paths = build_job_paths(self.job)
            user_bucket = self._project.cos_bucket_user_data_name
            results_key = paths.cos_results_key

            logger.debug("Retrieving results for job_id=[%s] from %s/%s", self.job.id, user_bucket, results_key)

            results_bytes = self._get_cos().get_object_bytes(bucket_name=user_bucket, key=results_key)
            if results_bytes:
                logger.info("Retrieved results for job_id=[%s] (%d bytes)", self.job.id, len(results_bytes))
                return results_bytes.decode("utf-8")

            logger.warning("No results found in COS for job_id=[%s]", self.job.id)
            return None

        except Exception as ex:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to retrieve results for job_id=[%s]: %s", self.job.id, ex)
            return None

    def stop(self) -> bool:
        """Delete the fleet to stop it if it is pending or running.

        Returns:
            ``True`` if the fleet was stopped, ``False`` if not stoppable.

        Raises:
            RunnerError: On API errors.
        """
        self._ensure_connected()
        if not self.job.fleet_id:
            raise RunnerError("Job has no fleet_id assigned")

        try:
            handler = self._get_handler()
            status_info = handler.get_job_status(self.job.fleet_id)
            current_status = (status_info.get("status") or "").lower()

            if current_status in {"running", "pending"}:
                handler.cancel_job(self.job.fleet_id, wait=False, delete=False)
                logger.info("Cancelled fleet [%s]", self.job.fleet_id)
                return True

            logger.info("Fleet [%s] not stoppable (status: %s)", self.job.fleet_id, current_status)
            return False

        except ApiException as ex:
            logger.error(
                "CE API error stopping fleet [%s]: status=%s reason=%s",
                self.job.fleet_id,
                ex.status,
                ex.reason,
            )
            raise RunnerError(f"Code Engine API error: {ex.reason}", ex) from ex
        except Exception as ex:
            logger.error("Failed to stop fleet [%s]: %s", self.job.fleet_id, ex)
            raise RunnerError(f"Unable to stop fleet [{self.job.fleet_id}]", ex) from ex

    def free_resources(self) -> bool:
        """Delete the fleet associated with this job.

        Returns:
            ``True`` if cleaned up (or already deleted), ``False`` on error.
        """
        # NOTE: fleet deletion disabled to preserve fleets for post-run inspection.
        # Re-enable after the demo.
        # if not self.job.fleet_id:
        #     logger.debug("No fleet_id to clean up for job_id=[%s]", self.job.id)
        #     return False
        #
        # try:
        #     self._get_handler().delete_job(self.job.fleet_id)
        #     logger.info("Deleted fleet [%s]", self.job.fleet_id)
        #     return True
        # except Exception as ex:  # pylint: disable=broad-exception-caught
        #     logger.warning("Failed to delete fleet [%s]: %s", self.job.fleet_id, ex)
        #     return False
        return False

    def _get_project(self) -> CodeEngineProject:
        """Return the job's assigned Code Engine project.

        The project is selected at job creation time (in ``RunJobSerializer.create``).
        This method only validates that the assignment is present and active.

        Returns:
            Active :class:`CodeEngineProject`.

        Raises:
            RunnerError: If no project is assigned or the assigned project is inactive.
        """
        project = self.job.code_engine_project
        if not project:
            raise RunnerError(f"No Code Engine project assigned to job '{self.job.id}'")
        if not project.active:
            raise RunnerError(f"Code Engine project '{project.project_name}' is not active")
        return project

    def _get_handler(self) -> FleetHandler:
        """Return the :class:`FleetHandler`, creating it lazily on first use.

        Token refresh is handled transparently: ``FleetHandler`` sets a
        ``refresh_api_key_hook`` on the swagger ``Configuration`` so the
        IAM bearer token is fetched fresh before every API request via
        ``IBMCloudClientProvider.auth.token`` (which calls
        ``IAMAuthenticator.token_manager.get_token()`` and auto-renews).

        Returns:
            Initialized :class:`FleetHandler`.

        Raises:
            RunnerError: If initialization fails.
        """
        if not self._project:
            self._project = self._get_project()

        if self._handler is None:
            try:
                ce_api_client = get_ce_auth(self._get_api_key(), self._project.region).api_client
                self._handler = FleetHandler(
                    ce_api_client=ce_api_client,
                    project_id=self._project.project_id,
                )
                logger.info("Initialized FleetHandler for project [%s]", self._project.project_name)
            except Exception as ex:
                name = self._project.project_name if self._project else "unassigned"
                raise RunnerError(f"Failed to initialize FleetHandler for project [{name}]", ex) from ex

        return self._handler

    def _get_cos(self) -> JobCOS:
        """Return the :class:`JobCOS`, creating it lazily on first use."""
        if not self._project:
            self._project = self._get_project()
        if self._cos is None:
            self._cos = get_cos_client(self._project)
        return self._cos

    def _upload_program_to_cos(self, paths: FleetJobPaths) -> None:
        """Dispatcher: uploads COS objects for the job before fleet submission.

        Dispatches to the appropriate upload method based on job type:
        - artifact set → :meth:`_upload_custom_image_entrypoint`
        - image set (no artifact) → :meth:`_upload_provider_image_entrypoint`

        Args:
            paths: Pre-computed paths from :func:`build_job_paths`.
        """
        if self.job.program.artifact:
            self._upload_custom_image_entrypoint(paths)
        elif self.job.program.image:
            self._upload_provider_image_entrypoint(paths)

    def _upload_custom_image_entrypoint(self, paths: FleetJobPaths) -> None:
        """Extract the program artifact tar and upload files to COS.

        Custom jobs: entrypoint → user bucket at function level; other files → user bucket at job level.
        Provider functions skip this — their files are pre-uploaded by the provider admin.

        Args:
            paths: Pre-computed paths from :func:`build_job_paths`.
        """
        program = self.job.program
        if not program.artifact:
            return

        user_bucket = self._project.cos_bucket_user_data_name

        # upload template
        template_name = "fleet_custom_job_wrapper.py"
        script = get_template(template_name).render(
            {"app_cmd": json.dumps(["python", paths.container_function_entrypoint])}
        )
        self._get_cos().upload_fileobj(
            fileobj=BytesIO(script.encode()),
            bucket_name=user_bucket,
            key=paths.cos_docker_entrypoint,
        )

        # upload user source files (including entrypoint)
        entrypoint_found = False
        try:
            with tarfile.open(program.artifact.path) as tar:
                for member in tar.getmembers():
                    if not member.isfile():
                        continue
                    extracted = tar.extractfile(member)
                    if extracted is None:
                        continue

                    if member.name == program.entrypoint:
                        entrypoint_found = True

                    key = f"{paths.cos_user_function_prefix}/{member.name}"

                    self._get_cos().upload_fileobj(fileobj=extracted, bucket_name=user_bucket, key=key)
                    logger.debug("Uploaded [%s] for job_id=%s to %s/%s", member.name, self.job.id, user_bucket, key)
        except tarfile.TarError as ex:
            raise RunnerError(f"Failed to read artifact for job_id=[{self.job.id}]", ex) from ex

        if not entrypoint_found:
            raise RunnerError(f"Entrypoint '{program.entrypoint}' not found in artifact for job_id=[{self.job.id}]")

    def _upload_provider_image_entrypoint(self, paths: FleetJobPaths) -> None:
        """Upload COS objects for a provider image job.

        Provider jobs: entrypoint (rendered from main.tmpl) and wrapper script →
        provider bucket at function scope; arguments → user bucket at job scope.

        Args:
            paths: Pre-computed paths from :func:`build_job_paths`.
        """
        program = self.job.program
        if not program.image:
            return
        if not program.provider:
            raise RunnerError("_upload_provider_image_entrypoint called on non-provider job")

        provider_bucket = self._project.cos_bucket_provider_data_name

        # upload wrapper script
        wrapper_script = get_template("fleet_provider_job_wrapper.py").render(
            {"app_cmd": json.dumps(["python", paths.container_function_entrypoint])}
        )
        self._get_cos().upload_fileobj(
            fileobj=BytesIO(wrapper_script.encode()),
            bucket_name=provider_bucket,
            key=paths.cos_docker_entrypoint,
        )
        logger.debug(
            "Uploaded provider wrapper for job_id=%s to %s/%s",
            self.job.id,
            provider_bucket,
            paths.cos_docker_entrypoint,
        )

        # upload rendered entrypoint template
        rendered = get_template("main.tmpl").render(
            {
                "mount_path": settings.CUSTOM_IMAGE_PACKAGE_PATH,
                "package_name": settings.CUSTOM_IMAGE_PACKAGE_NAME,
            }
        )
        self._get_cos().upload_fileobj(
            fileobj=BytesIO(rendered.encode()),
            bucket_name=provider_bucket,
            key=paths.cos_function_entrypoint,
        )
        logger.debug(
            "Uploaded template entrypoint for job_id=%s to %s/%s",
            self.job.id,
            provider_bucket,
            paths.cos_function_entrypoint,
        )

    def _get_fleet_name(self) -> str:
        """Return the fleet name from the CE API, falling back to ``"job-{id}"``.

        Returns:
            Fleet name string.
        """
        try:
            info = self._get_handler().get_job_status(self.job.fleet_id)
            return info.get("name") or f"job-{self.job.id}"
        except Exception as ex:  # pylint: disable=broad-exception-caught
            logger.warning("Could not retrieve fleet name for [%s]: %s", self.job.fleet_id, ex)
            return f"job-{self.job.id}"

    def _is_cos_configured(self) -> bool:
        """Return ``True`` if the COS project fields required for this job type are set.

        Provider jobs require both user and provider buckets. Custom jobs only
        require the user bucket (the provider bucket is not used).

        Returns:
            ``True`` when COS is sufficiently configured for this job.
        """
        if not self._project:
            return False
        if self.job.program.provider:
            return all(
                [
                    self._project.cos_bucket_provider_data_name,
                    self._project.cos_bucket_user_data_name,
                    self._project.cos_instance_name,
                    self._project.cos_key_name,
                ]
            )
        # Custom functions don't use cos_bucket_provider_data_name
        return all(
            [
                self._project.cos_bucket_user_data_name,
                self._project.cos_instance_name,
                self._project.cos_key_name,
            ]
        )

    def _get_api_key(self) -> str:
        """Return the IBM Cloud API key from Django settings.

        Returns:
            API key string.

        Raises:
            RunnerError: If not configured.
        """
        api_key = settings.IBM_CLOUD_API_KEY
        if not api_key:
            raise RunnerError("IBM_CLOUD_API_KEY not configured in settings")
        return api_key

    def _get_image(self) -> str:
        """Return the container image for the fleet.

        Uses ``program.image`` if set, otherwise falls back to
        ``settings.FLEETS_DEFAULT_IMAGE``.

        Returns:
            Image reference string.
        """
        if not self.job.program:
            raise RunnerError("Job has no program assigned")
        if self.job.program.image:
            return self.job.program.image
        return settings.FLEETS_DEFAULT_IMAGE

    def _parse_compute_profile(self) -> tuple[str, str, dict | None]:
        """Parse compute_profile into (cpu, memory, gpu).

        Supports formats like ``gx3d-24x120x1a100p`` or ``24x120x2a100p``.
        The resource part is ``{cpu}x{memory}[x{count}{model}]``.

        Returns:
            Tuple of (cpu_limit, memory_limit, scale_gpu) where scale_gpu
            is the V2GPUScalePrototype dict or ``None`` when no GPU is
            specified in the profile.
        """
        profile = self.job.compute_profile or getattr(settings, "DEFAULT_COMPUTE_PROFILE", "cx3d-4x16")

        # Strip optional prefix (e.g. "gx3d-" or "cx3d-")
        match = re.match(r"^[a-z]+\d[a-z\d]*-(.+)$", profile)
        resources = match.group(1) if match else profile

        # Parse: {cpu}x{memory}[x{count}{model}]
        parts = re.match(r"^(\d+)x(\d+)(?:x(\d+)([a-z]\w*))?$", resources)
        if not parts:
            logger.warning("Could not parse compute_profile [%s], using defaults", profile)
            return (
                str(getattr(settings, "FLEETS_DEFAULT_CPU_LIMIT", "24")),
                str(getattr(settings, "FLEETS_DEFAULT_MEMORY_LIMIT", "120G")),
                None,
            )

        cpu = parts.group(1)
        memory = f"{parts.group(2)}G"
        scale_gpu = None
        if parts.group(3) and parts.group(4):
            # e.g. "1a100p" → {"preferences": [{"family": "a100p", "allocation": "1"}]}
            scale_gpu = {"preferences": [{"family": parts.group(4), "allocation": parts.group(3)}]}

        return cpu, memory, scale_gpu

    def _get_max_instances(self) -> int:
        """Return the maximum number of fleet instances.

        Uses ``job.config.workers`` if set, otherwise falls back to
        ``settings.FLEETS_DEFAULT_MAX_INSTANCES`` (default ``1``).

        Returns:
            Max instances as integer.
        """
        if self.job.config and getattr(self.job.config, "workers", None):
            return int(self.job.config.workers)
        return int(getattr(settings, "FLEETS_DEFAULT_MAX_INSTANCES", 1))

    def _map_fleet_status(self, fleet_status: str) -> str:
        """Map a CE fleet status string to a :attr:`Job.STATUS` constant.

        Args:
            fleet_status: Raw fleet status from Code Engine.

        Returns:
            Corresponding ``Job.STATUS`` constant.
        """
        status_map = {
            "pending": Job.PENDING,
            "running": Job.RUNNING,
            "succeeded": Job.SUCCEEDED,
            "successful": Job.SUCCEEDED,
            "failed": Job.FAILED,
            "stopped": Job.STOPPED,
            "cancelled": Job.STOPPED,
            "canceled": Job.STOPPED,
            "canceling": Job.STOPPED,
        }
        return status_map.get(fleet_status.lower(), Job.PENDING)
