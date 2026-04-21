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

"""
Fleet job lifecycle manager.

Implements the :class:`FleetHandler` API for managing fleet jobs:

- Submit a job
- Check the status of a job
- Cancel a job
- Delete a job

Worker monitoring and COS operations are delegated to sub-managers
accessible via :attr:`FleetHandler.workers` and :attr:`FleetHandler.cos`.

Configuration builders for volume mounts, environment variables, and
run commands are available as standalone functions in
:mod:`core.services.ibm_cloud.code_engine.fleets.fleet_utils`.

Example usage::

    handler = FleetHandler(
        client_provider=client_provider,
        project_id=project_id,
    )

    # Fleet CRUD
    handler.submit_job(name="my-fleet", ...)
    handler.get_job_status("my-fleet")
    handler.cancel_job("my-fleet", wait=True, delete=True)

    # Workers (sub-manager)
    handler.workers.list(fleet_id="...")
    handler.workers.wait(fleet_id="...", timeout=120)

    # COS (sub-manager)
    handler.cos.logs(bucket_name="...", log_key="...")
"""

from __future__ import annotations

import logging
import re  # used by _UUID_RE module-level constant
import time
from functools import cached_property
from typing import Any

from swagger_client import ApiClient, Configuration
from swagger_client.api.fleets_api import FleetsApi
from swagger_client.rest import ApiException

from core.services.ibm_cloud.clients import IBMCloudClientProvider
from core.services.ibm_cloud.code_engine.fleets.cos import JobCOS
from core.services.ibm_cloud.code_engine.fleets.fleet_workers import JobWorkers

logger = logging.getLogger("FleetHandler")

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class FleetHandler:
    """
    Uses the swagger-generated FleetsAPI to manage jobs (fleets).

    Initialization requires:
      - IBMCloudClientProvider: initialized IBMCloud client provider class with region specified
      - project_id: Code Engine project UUID

    Sub-managers:
      - ``handler.workers`` — worker lifecycle operations
      - ``handler.cos`` — Cloud Object Storage operations
    """

    def __init__(
        self,
        *,
        client_provider: IBMCloudClientProvider,
        project_id: str,
        cos_config: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the class FleetHandler.

        Args:
            client_provider:
                Initialized :class:`IBMCloudClientProvider`. The provider must contain
                authenticated state, including a valid account ID and a specified region.
            project_id:
                Code Engine project UUID.
            cos_config:
                Optional COS configuration for log retrieval. Dictionary with keys:
                - hmac_access_key_id: HMAC access key ID.
        """
        self.client_provider = client_provider
        self.project_id = project_id
        self.cos_config = cos_config

        cfg = Configuration()
        cfg.host = self.client_provider.config.code_engine_url
        cfg.api_key["Authorization"] = self.client_provider.auth.token
        cfg.api_key_prefix["Authorization"] = "Bearer"

        self._client = ApiClient(cfg)
        self._fleets_api = FleetsApi(self._client)

    @cached_property
    def workers(self) -> JobWorkers:
        """Worker lifecycle manager bound to this job handler."""
        return JobWorkers(self)

    @cached_property
    def cos(self) -> JobCOS:
        """COS operations manager bound to this job handler."""
        return JobCOS(self)

    def submit_job(  # pylint: disable=too-many-arguments
        self,
        *,
        name: str,
        image_reference: str,
        network_placements: list[dict[str, Any]],
        scale_cpu_limit: str,
        scale_memory_limit: str,
        scale_max_instances: int,
        scale_retry_limit: int,
        tasks_specification: dict[str, Any],
        tasks_state_store: dict[str, Any],
        image_secret: str | None = None,
        extra_fields: dict[str, Any] | None = None,
    ) -> Any:
        """
        Submit a job by creating a Fleet via POST /projects/{project_id}/fleets.

        Args:
          - name: name of the fleet
          - image_reference: fleet image container
          - network_placements: list of type, reference e.g. [{"type": "subnet_pool", "reference": subnet_pool_id}]
          - scale_cpu_limit: Number of CPUs set for each task in the fleet
          - scale_memory_limit: memory for fleet worker (e.g., "2G")
          - scale_max_instances: number of tasks are processed simultaneously, must be >=1
          - scale_retry_limit: number of times to rerun an instance of the task, must be >= 0
          - tasks_specification: input for tasks based on indices e.g. {"indices": "0"}
          - tasks_state_store: name of the persistent data store created for this Code Engine project

        OPTIONAL:
          - image_secret: registry access secret, for private images
          - extra_fields: any additional valid FleetPrototype properties
                          (e.g., command/args, scale_max_execution_time, etc.)

        Returns:
            The object returned by the swagger client's create_fleet call.
        """
        body: dict[str, Any] = {
            "name": name,
            "image_reference": image_reference,
            "network_placements": network_placements,
            "scale_cpu_limit": scale_cpu_limit,
            "scale_memory_limit": scale_memory_limit,
            "scale_max_instances": scale_max_instances,
            "scale_retry_limit": scale_retry_limit,
            "tasks_specification": tasks_specification,
            "tasks_state_store": tasks_state_store,
        }
        if image_secret:
            body["image_secret"] = image_secret
        if extra_fields:
            body.update(extra_fields)

        try:
            created = self._fleets_api.create_fleet(project_id=self.project_id, body=body)
            return created
        except ApiException as exc:
            logger.error(
                "create_fleet failed: project_id=%s status=%s reason=%s",
                self.project_id,
                exc.status,
                exc.reason,
            )
            raise

    def get_job_status(self, identifier: str) -> dict[str, Any]:
        """
        Get the current status of a fleet ("job") by fleet UUID or name.

        Args:
            identifier: Either the fleet UUID (e.g., '15314cc3-...') or the fleet name.

        Returns:
            A dict with a stable subset of status information, e.g.:
            {
                "id": "...",
                "name": "...",
                "status": "...",
                "desired_instances": 1,
                "running_instances": 1,
                "created_at": "2026-02-17T01:23:45Z",
                "updated_at": "2026-02-17T01:55:00Z",
                "raw": <the full SDK model as dict>
            }

        Raises:
            ValueError: if identifier is a name and cannot be resolved.
            ApiException: if the GET call fails (e.g., 404/403).
        """
        fleet_id = self._resolve_fleet_id(identifier)

        fleet: Any = self._fleets_api.get_fleet(project_id=self.project_id, id=fleet_id)

        as_dict = fleet.to_dict() if hasattr(fleet, "to_dict") else dict(fleet)

        status = as_dict.get("status") or as_dict.get("state")
        desired = as_dict.get("scale_max_instances") or as_dict.get("desired_instances")
        running = as_dict.get("running_instances")
        created = as_dict.get("created_at") or as_dict.get("created")
        updated = as_dict.get("updated_at") or as_dict.get("updated")

        summary = {
            "id": as_dict.get("id"),
            "name": as_dict.get("name"),
            "status": status,
            "desired_instances": desired,
            "running_instances": running,
            "created_at": created,
            "updated_at": updated,
            "raw": as_dict,
        }
        return summary

    def _resolve_fleet_id(self, identifier: str) -> str:
        """Resolve a fleet identifier (UUID or name) to a fleet UUID.

        If the identifier matches the UUID pattern it is returned directly.
        Otherwise the fleet list is searched for an exact name match.

        Args:
            identifier: Fleet UUID (``8-4-4-4-12`` hex pattern) or fleet name.

        Returns:
            Fleet UUID string.

        Raises:
            ValueError: If the identifier is a name that cannot be resolved.
            ApiException: If the list_fleets call fails.
        """

        if _UUID_RE.match(identifier):
            return identifier

        resp = self._fleets_api.list_fleets(project_id=self.project_id, limit=100)
        items = getattr(resp, "fleets", None) or []
        for fleet in items:
            if getattr(fleet, "name", None) == identifier:
                fid = getattr(fleet, "id", None)
                if fid:
                    return fid

        raise ValueError(f"Fleet named '{identifier}' was not found in project {self.project_id}.")

    def cancel_job(
        self,
        identifier: str,
        *,
        wait: bool = True,
        delete: bool = False,
        timeout_seconds: int = 300,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        """
        Attempt to cancel a fleet ("job") only if it is pending or running, then optionally wait
        for terminal and optionally delete.

        Steps:
        1) Resolve identifier (name or UUID) to a fleet UUID.
        2) Inspect status. If 'pending' or 'running', issue cancel (best-effort). Otherwise skip cancel.
        3) If wait=True, poll until the fleet reaches a terminal state (or disappears).
        4) If delete=True, attempt to delete. Treat 404 as success.

        Args:
            identifier: Fleet UUID or fleet name.
            wait: If True, poll the fleet until terminal after the cancel decision.
            delete: If True, delete the fleet after optional wait.
            timeout_seconds: Max time to wait for terminal state when wait=True.
            poll_interval_seconds: Delay between polls.

        Raises:
            ValueError: If identifier is a name that cannot be resolved.
            ApiException: If delete_fleet fails with an error other than 404.
            AssertionError: If waiting is enabled and the fleet never reaches terminal before timeout.
        """
        fleet_id = self._resolve_fleet_id(identifier)

        # Decide whether we should cancel based on current status.
        should_attempt_cancel = False
        try:
            info = self.get_job_status(fleet_id)
            status = (info.get("status") or "").lower()
            should_attempt_cancel = status in {"pending", "running"}
        except ApiException as exc:
            if exc.status == 404:
                should_attempt_cancel = False
            else:
                should_attempt_cancel = True

        if should_attempt_cancel:
            try:
                self._fleets_api.cancel_fleet(project_id=self.project_id, id=fleet_id)
            except ApiException as exc:
                if exc.status != 404:
                    raise

        # Optionally wait for terminal to avoid delete races.
        if wait:
            self._wait_until_terminal_or_canceled(
                fleet_id,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )

        # Optionally delete; must succeed or be already deleted; raise for non-404 errors.
        if delete:
            try:
                self._fleets_api.delete_fleet(project_id=self.project_id, id=fleet_id)
            except ApiException as exc:
                if exc.status != 404:
                    raise

    def delete_job(self, identifier: str) -> None:
        """
        Delete a fleet ("job") by name or UUID without attempting a cancel.

        Args:
            identifier: Fleet UUID or fleet name.

        Raises:
            ValueError: If identifier is a name that cannot be resolved.
            ApiException: If delete_fleet fails with an error other than 404.
        """
        fleet_id = self._resolve_fleet_id(identifier)
        try:
            self._fleets_api.delete_fleet(project_id=self.project_id, id=fleet_id)
        except ApiException as exc:
            if exc.status != 404:
                raise

    def _wait_until_terminal_or_canceled(
        self,
        fleet_id: str,
        *,
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> None:
        """Poll the fleet until terminal, disappeared, or timeout.

        Args:
            fleet_id: Fleet UUID to poll.
            timeout_seconds: Maximum seconds to wait before raising.
            poll_interval_seconds: Seconds between each status check.

        Raises:
            ApiException: If get_fleet fails with a non-404 error.
            AssertionError: If timeout is reached before a terminal state is observed.
        """
        terminal = {"succeeded", "successful", "failed", "canceled"}
        deadline = time.time() + timeout_seconds

        while True:
            try:
                info = self.get_job_status(fleet_id)
                status = (info.get("status") or "").lower()
                if status in terminal:
                    return
            except ApiException as exc:
                if exc.status == 404:
                    return
                raise

            if time.time() >= deadline:
                raise AssertionError(
                    f"Timed out waiting for fleet {fleet_id} to reach a terminal state."
                )
            time.sleep(poll_interval_seconds)
