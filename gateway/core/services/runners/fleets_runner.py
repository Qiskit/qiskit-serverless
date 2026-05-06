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

import io
import json
import logging
import re
import tarfile
import time
from collections import OrderedDict

from django.conf import settings
from core.ibm_cloud.code_engine.ce_client.rest import ApiException

from core.models import Job, CodeEngineProject
from core.services.runners.abstract_runner import AbstractRunner, RunnerError
from core.ibm_cloud.clients import IBMCloudClientProvider, COS_PUBLIC_URL_TEMPLATE
from core.utils import decrypt_env_vars
from core.ibm_cloud.code_engine.fleets.handler import FleetHandler
from core.ibm_cloud.code_engine.fleets.utils import (
    build_run_commands,
    build_run_env_variables,
    build_run_volume_mounts,
)
from core.services.storage.arguments_storage import ArgumentsStorage

logger = logging.getLogger("FleetsRunner")

LOG_FILTER_KEY = "[public]"
LOG_FILENAME = "logs.log"


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
                "Submitting job [%s] as fleet [%s] to project [%s]",
                self.job.id,
                fleet_name,
                self._project.project_name,
            )

            extra_fields: dict = {}

            cpu_limit, memory_limit, scale_gpu = self._parse_compute_profile()
            logger.info(
                "Job [%s] profile [%s] → cpu=%s memory=%s gpu=%s",
                self.job.id,
                self.job.compute_profile or "default",
                cpu_limit,
                memory_limit,
                scale_gpu,
            )
            if scale_gpu:
                extra_fields["scale_gpu"] = scale_gpu

            if self._is_cos_configured():
                paths = self._build_cos_paths()
                job_id = str(self.job.id)

                run_volume_mounts = build_run_volume_mounts(
                    mounts=[
                        (paths["user_mount_path"], self._project.pds_name_users, paths["user_function_prefix"]),
                        (
                            paths["provider_mount_path"],
                            self._project.pds_name_providers,
                            paths["provider_function_prefix"],
                        ),
                    ]
                )
                run_env_variables = build_run_env_variables(
                    primary_mount_path=f"{paths['provider_mount_path']}/jobs/{job_id}",
                    primary_log_filename=LOG_FILENAME,
                    secondary_mount_path=f"{paths['user_mount_path']}/jobs/{job_id}",
                    secondary_log_filename=LOG_FILENAME,
                    secondary_log_filter_key=LOG_FILTER_KEY,
                )
                run_env_variables.append(
                    {"type": "literal", "name": "JOB_ID_GATEWAY", "value": job_id},
                )

                gateway_env = self._build_gateway_env_vars()
                run_env_variables.extend(gateway_env)
                run_commands = build_run_commands(
                    app_run_commands=["python", f"{paths['provider_mount_path']}/{self.job.program.entrypoint}"],
                    secondary_log_filter_key=LOG_FILTER_KEY,
                )
                extra_fields.update(
                    {
                        "run_volume_mounts": run_volume_mounts,
                        "run_env_variables": run_env_variables,
                        "run_commands": run_commands,
                    }
                )
                _retry_on_rate_limit(lambda: self._upload_arguments_to_cos(handler, paths))
                _retry_on_rate_limit(lambda: self._upload_artifact_to_cos(handler, paths))
                logger.info(
                    "COS configured for job [%s]: user_key=[%s] provider_key=[%s]",
                    self.job.id,
                    paths["user_log_key"],
                    paths["provider_log_key"],
                )
            else:
                logger.info("COS not available for job [%s]", self.job.id)

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

            logger.info("Submitted job [%s] as fleet [%s]", self.job.id, fleet_id)
            self.job.fleet_id = fleet_id

        except ApiException as ex:
            logger.error(
                "CE API error submitting job [%s]: status=%s reason=%s",
                self.job.id,
                ex.status,
                ex.reason,
            )
            raise RunnerError(f"Code Engine API error: {ex.reason}", ex) from ex
        except RunnerError:
            raise
        except Exception as ex:
            logger.error("Failed to submit job [%s]: %s", self.job.id, ex)
            raise RunnerError(f"Failed to submit job [{self.job.id}] to Code Engine Fleets", ex) from ex

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
        """Return user (``[public]``-filtered) logs from the user COS bucket.

        Returns:
            Log content or ``None``.
        """
        return self._get_logs_from_cos(
            bucket_field="cos_bucket_user_data_name",
            log_key_field="user_log_key",
            label="user",
        )

    def provider_logs(self) -> str | None:
        """Return provider (unfiltered) logs from the provider COS bucket.

        Returns:
            Log content or ``None``.
        """
        return self._get_logs_from_cos(
            bucket_field="cos_bucket_provider_data_name",
            log_key_field="provider_log_key",
            label="provider",
        )

    def get_result_from_cos(self) -> str | None:
        """Retrieve job results from COS.

        Results are written by the container at
        ``{user_job_prefix}/results.json``.

        Returns:
            JSON string or ``None`` if COS is not configured or the file is absent.
        """
        if not self._is_cos_configured():
            logger.debug("COS not configured for job [%s]", self.job.id)
            return None

        try:
            handler = self._get_handler()
            paths = self._build_cos_paths()
            user_bucket = self._project.cos_bucket_user_data_name
            results_key = f"{paths['user_job_prefix']}/results.json"

            logger.debug("Retrieving results for job [%s] from %s/%s", self.job.id, user_bucket, results_key)

            results_bytes = handler.cos.get_object_bytes(bucket_name=user_bucket, key=results_key)
            if results_bytes:
                logger.info("Retrieved results for job [%s] (%d bytes)", self.job.id, len(results_bytes))
                return results_bytes.decode("utf-8")

            logger.warning("No results found in COS for job [%s]", self.job.id)
            return None

        except Exception as ex:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to retrieve results for job [%s]: %s", self.job.id, ex)
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
        #     logger.debug("No fleet_id to clean up for job [%s]", self.job.id)
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

    def _get_or_assign_project(self) -> CodeEngineProject:
        """Return the job's Code Engine project, assigning one if not yet set.

        Zone resolution: looks up the compute profile in ``FLEETS_PROFILE_ZONE_MAP``.
        Profiles absent from the map (or mapped to ``"any"``) fall back to the
        multi-zone project (zone is null/blank).

        Returns:
            Active :class:`CodeEngineProject`.

        Raises:
            RunnerError: If no active project is available.
        """
        if self.job.code_engine_project:
            project = self.job.code_engine_project
            if not project.active:
                raise RunnerError(f"Code Engine project '{project.project_name}' is not active")
            return project

        profile_zone_map: dict = settings.FLEETS_PROFILE_ZONE_MAP
        zone = profile_zone_map.get(self.job.compute_profile or "")
        qs = CodeEngineProject.objects.filter(active=True)
        if zone and zone != "any":
            project = qs.filter(zone=zone).first()
            if not project:
                raise RunnerError(f"No active Code Engine project for zone '{zone}'")
        else:
            project = qs.filter(zone__isnull=True).first() or qs.filter(zone="").first() or qs.first()
        if not project:
            raise RunnerError("No active Code Engine project available")

        self.job.code_engine_project = project
        self.job.save()
        logger.info("Assigned project [%s] to job [%s]", project.project_name, self.job.id)
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
            self._project = self._get_or_assign_project()

        if self._handler is None:
            try:
                client_provider = IBMCloudClientProvider(
                    api_key=self._get_api_key(),
                    region=self._project.region,
                )
                cos_config = self._get_handler_cos_config()
                self._handler = FleetHandler(
                    client_provider=client_provider,
                    project_id=self._project.project_id,
                    cos_config=cos_config,
                )
                label = "with COS" if cos_config else "without COS"
                logger.info("Initialized FleetHandler %s for project [%s]", label, self._project.project_name)
            except Exception as ex:
                name = self._project.project_name if self._project else "unassigned"
                raise RunnerError(f"Failed to initialize FleetHandler for project [{name}]", ex) from ex

        return self._handler

    def _build_gateway_env_vars(self) -> list[dict[str, str]]:
        """Extract job env vars so the container can call save_result() and use Qiskit Runtime."""
        env = json.loads(self.job.env_vars)
        env = decrypt_env_vars(env)

        return [{"type": "literal", "name": k, "value": v} for k, v in env.items() if v]

    def _build_cos_paths(self) -> dict[str, str]:
        """Build COS key prefixes and container mount paths for the job.

        Both PDS volumes mount at function level so all jobs sharing the same
        program share function-level files while having isolated job-level
        directories for arguments, logs, and results.

        Returns:
            Dict with function/job prefixes, COS log/argument keys, and
            container mount paths.
        """
        author_id = str(self.job.author.id)
        provider_name = self.job.program.provider.name if self.job.program and self.job.program.provider else "default"
        program_title = self.job.program.title if self.job.program else "unknown"
        job_id = str(self.job.id)

        user_function_prefix = f"users/{author_id}/provider_functions/{provider_name}/{program_title}"
        provider_function_prefix = f"providers/{provider_name}/{program_title}"
        user_job_prefix = f"{user_function_prefix}/jobs/{job_id}"
        provider_job_prefix = f"{provider_function_prefix}/jobs/{job_id}"

        return {
            "user_function_prefix": user_function_prefix,
            "provider_function_prefix": provider_function_prefix,
            "user_job_prefix": user_job_prefix,
            "provider_job_prefix": provider_job_prefix,
            "user_log_key": f"{user_job_prefix}/{LOG_FILENAME}",
            "provider_log_key": f"{provider_job_prefix}/{LOG_FILENAME}",
            "user_arguments_key": f"{user_job_prefix}/arguments.json",
            "user_mount_path": "/data",
            "provider_mount_path": "/function_data",
        }

    def _upload_arguments_to_cos(self, handler: FleetHandler, paths: dict[str, str]) -> None:
        """Upload job arguments from local storage to the COS user bucket.

        Reads from :class:`ArgumentsStorage` and uploads to
        ``{user_job_prefix}/arguments.json``. Unwraps a single-key
        ``{"arguments": ...}`` envelope if present.

        Args:
            handler: Initialized :class:`FleetHandler` with COS access.
            paths: Dict from :meth:`_build_cos_paths`.
        """
        program = self.job.program
        provider_name = program.provider.name if program.provider else None
        storage = ArgumentsStorage(self.job.author.username, program.title, provider_name)
        content = storage.get(str(self.job.id)) or "{}"

        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict) and list(parsed.keys()) == ["arguments"]:
                content = json.dumps(parsed["arguments"])
        except (json.JSONDecodeError, TypeError):
            pass

        user_bucket = self._project.cos_bucket_user_data_name
        handler.cos.upload_fileobj(
            fileobj=io.BytesIO(content.encode("utf-8")),
            bucket_name=user_bucket,
            key=paths["user_arguments_key"],
        )
        logger.info("Uploaded arguments for job [%s] to %s/%s", self.job.id, user_bucket, paths["user_arguments_key"])

    def _upload_artifact_to_cos(self, handler: FleetHandler, paths: dict[str, str]) -> None:
        """Extract the program artifact tar and upload files to COS.

        Entrypoint → provider bucket (accessible at ``/function_data/{entrypoint}``).
        All other files → user bucket (accessible at ``/data/{filename}``).

        Provider functions skip this — their files are pre-uploaded by the
        provider admin.

        Args:
            handler: Initialized :class:`FleetHandler` with COS access.
            paths: Dict from :meth:`_build_cos_paths`.
        """
        program = self.job.program
        if not program.artifact:
            return

        provider_bucket = self._project.cos_bucket_provider_data_name
        user_bucket = self._project.cos_bucket_user_data_name
        entrypoint_name = program.entrypoint

        try:
            with tarfile.open(program.artifact.path) as tar:
                for member in tar.getmembers():
                    if not member.isfile():
                        continue
                    extracted = tar.extractfile(member)
                    if extracted is None:
                        continue

                    if member.name == entrypoint_name:
                        bucket_name = provider_bucket
                        key = f"{paths['provider_function_prefix']}/{member.name}"
                    else:
                        bucket_name = user_bucket
                        key = f"{paths['user_function_prefix']}/{member.name}"

                    handler.cos.upload_fileobj(fileobj=extracted, bucket_name=bucket_name, key=key)
                    logger.debug("Uploaded [%s] for job [%s] to %s/%s", member.name, self.job.id, bucket_name, key)
        except tarfile.TarError as ex:
            raise RunnerError(f"Failed to read artifact for job [{self.job.id}]", ex) from ex

        logger.info("Uploaded artifact for job [%s] (entrypoint→provider, data→user)", self.job.id)

    def _get_logs_from_cos(self, bucket_field: str, log_key_field: str, label: str) -> str | None:
        """Retrieve logs from a COS bucket.

        Args:
            bucket_field: :class:`CodeEngineProject` attribute name for the bucket.
            log_key_field: Key in :meth:`_build_cos_paths` for the COS object key.
            label: Human-readable label (``"user"`` or ``"provider"``) for log messages.

        Returns:
            Log content string or ``None``.

        Raises:
            RunnerError: On API errors.
        """
        self._ensure_connected()
        if not self.job.fleet_id:
            raise RunnerError("Job has no fleet_id assigned")

        try:
            handler = self._get_handler()

            if not self._is_cos_configured():
                return "Logs not available (COS logging not configured for this project)"

            bucket_name = getattr(self._project, bucket_field, None)
            if not bucket_name:
                return f"Logs not available ({label} COS bucket not configured)"

            paths = self._build_cos_paths()
            log_key = paths[log_key_field]

            logger.info(
                "Retrieving %s logs for fleet [%s]: bucket=[%s] key=[%s]",
                label,
                self.job.fleet_id,
                bucket_name,
                log_key,
            )

            logs = handler.cos.logs(
                bucket_name=bucket_name,
                log_key=log_key,
                save_locally=False,
                wait_for_availability=True,
                timeout=60,
            )

            if logs:
                logger.info("Retrieved %s logs for fleet [%s]", label, self.job.fleet_id)
                return logs

            return "Logs not yet available"

        except ApiException as ex:
            logger.error(
                "CE API error getting %s logs for fleet [%s]: status=%s reason=%s",
                label,
                self.job.fleet_id,
                ex.status,
                ex.reason,
            )
            raise RunnerError(f"Code Engine API error: {ex.reason}", ex) from ex
        except Exception as ex:
            logger.error("Failed to get %s logs for fleet [%s]: %s", label, self.job.fleet_id, ex)
            raise RunnerError(f"Unable to get {label} logs for fleet [{self.job.fleet_id}]", ex) from ex

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
        """Return ``True`` if all four COS project fields are set.

        Returns:
            ``True`` when COS is fully configured.
        """
        if not self._project:
            return False
        return all(
            [
                self._project.cos_bucket_user_data_name,
                self._project.cos_bucket_provider_data_name,
                self._project.cos_instance_name,
                self._project.cos_key_name,
            ]
        )

    def _get_handler_cos_config(self) -> dict | None:
        """Build the ``cos_config`` dict for :class:`FleetHandler`.

        Returns ``None`` when the project fields or the secret name are
        not configured.

        Returns:
            COS config dict or ``None``.
        """
        if not self._project or not self._is_cos_configured():
            return None

        hmac_secret_name = settings.CE_HMAC_SECRET_NAME
        if not hmac_secret_name:
            logger.debug("No HMAC credentials configured for project [%s]", self._project.project_name)
            return None

        cos_config: dict = {
            "bucket_region": self._project.region,
            "hmac_secret_name": hmac_secret_name,
        }
        if getattr(settings, "CE_COS_USE_PUBLIC_ENDPOINT", False):
            cos_config["cos_endpoint_url"] = COS_PUBLIC_URL_TEMPLATE.format(region=self._project.region)
        return cos_config

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
