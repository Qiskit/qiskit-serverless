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
:mod:`qf_fleets_client.api.job.utils`.

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

from __future__ import annotations  # optional; okay to keep

import time
from typing import Any
import re
import time
from functools import cached_property
from typing import Any

from swagger_client import ApiClient, Configuration
from swagger_client.api.fleets_api import FleetsApi
from swagger_client.rest import ApiException

from ...clients import IBMCloudClientProvider

from ...cos import JobCOS
from .fleet_workers import JobWorkers


class FleetHandler:
    # pylint: disable=too-few-public-methods
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
                - resource_group_id: Resource group ID
                - cos_name: COS instance name
                - cos_key_name: COS key name
                - bucket_name: COS bucket name for logs
                - bucket_region: COS bucket region (defaults to client_provider region)
                - hmac_secret_name: Optional CE HMAC secret name. When provided, HMAC
                  credentials are resolved from the existing CE secret instead of
                  calling the COS Resource Controller API.
                - hmac_secret_access_key: Optional CE HMAC secret key. When provided,
                  hmac_secret_name is ignored.
                - hmac_access_key_id: Optional CE HMAC secret key id. When provided,
                  hmac_secret_name is ignored.
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
            print(
                "create_fleet failed: project_id=%s status=%s reason=%s",
                self.project_id,
                getattr(exc, "status", None),
                getattr(exc, "reason", None),
            )
            raise

    def list_workers(self, *, fleet_id: str) -> list[Any]:
        """
        List all workers for a given fleet.

        This is a public wrapper around the internal _fleets_api.list_fleet_workers() method.

        Args:
            fleet_id: The ID of the fleet

        Returns:
            List of worker objects from the API

        Raises:
            ApiException: If the API call fails

        Example:
            >>> handler = FleetHandler(client_provider=provider, project_id=project_id)
            >>> workers = handler.list_workers(fleet_id="fdb395e9-be32-43a8-9a42-6bd9a2e1623d")
            >>> for worker in workers:
            ...     print(f"Worker: {worker.name}, Status: {worker.status}")
        """
        try:
            workers_response = self._fleets_api.list_fleet_workers(
                project_id=self.project_id, fleet_id=fleet_id
            )

            if hasattr(workers_response, "workers") and workers_response.workers:
                return workers_response.workers
            return []

        except ApiException as exc:
            print(
                "list_fleet_workers failed: project_id=%s fleet_id=%s status=%s reason=%s",
                self.project_id,
                fleet_id,
                getattr(exc, "status", None),
                getattr(exc, "reason", None),
            )
            raise

    def wait_for_workers(
        self, *, fleet_id: str, timeout: int = 60, poll_interval: int = 5
    ) -> list[Any]:
        """
        Wait for workers to be created for a fleet, with timeout and polling.

        This method polls the fleet workers API until at least one worker is found,
        or until the timeout is reached.

        Args:
            fleet_id: The ID of the fleet
            timeout: Maximum time to wait in seconds (default: 60)
            poll_interval: Time between polling attempts in seconds (default: 5)

        Returns:
            List of worker objects once found

        Raises:
            TimeoutError: If no workers are found within the timeout period
            ApiException: If the API call fails with a non-404 error

        Example:
            >>> handler = FleetHandler(client_provider=provider, project_id=project_id)
            >>> workers = handler.wait_for_workers(
            ...     fleet_id="fdb395e9-be32-43a8-9a42-6bd9a2e1623d",
            ...     timeout=120,
            ...     poll_interval=3
            ... )
            >>> print(f"Found {len(workers)} worker(s)")
        """
        start_time = time.perf_counter()

        while True:
            elapsed_time = time.perf_counter() - start_time

            if elapsed_time >= timeout:
                raise TimeoutError(
                    f"No workers were created for fleet {fleet_id} after waiting {timeout} seconds"
                )

            try:
                workers = self.list_workers(fleet_id=fleet_id)

                if workers:
                    return workers

                time.sleep(poll_interval)

            except ApiException as exc:
                # If it's a 404, the fleet might not be ready yet
                if exc.status == 404:
                    time.sleep(poll_interval)
                    continue
                raise

    def get_worker_resource_consumption(
        self,
        *,
        fleet_id: str,
        worker_name: str,
    ) -> dict[str, Any]:
        """
        Get resource consumption details for a specific fleet worker.

        This method retrieves worker information including vCPU, memory, GPU allocation,
        and duration based on created_at/finished_at timestamps.

        Args:
            fleet_id: The ID of the fleet
            worker_name: The name of the worker

        Returns:
            Dictionary containing:
            - worker: The raw V2Worker object from the API
            - profile: Worker profile string (e.g., "cxf-2x4")
            - created_at: Timestamp when worker was created
            - finished_at: Timestamp when worker finished (if completed)
            - duration_seconds: Duration in seconds (if finished)
            - status: Current worker status
            - zone: Availability zone the worker is located in
            - address: Address at which the worker is accessible

        Example:
            >>> handler = FleetHandler(client_provider=provider, project_id=project_id)
            >>> consumption = handler.get_worker_resource_consumption(
            ...     fleet_id="fdb395e9-be32-43a8-9a42-6bd9a2e1623d",
            ...     worker_name="fleet-fdb395e9-be32-43a8-9a42-6bd9a2e1623d-0"
            ... )
            >>> print(f"Profile: {consumption['profile']}")
            >>> print(f"Duration: {consumption['duration_seconds']} seconds")
        """
        try:
            worker = self._fleets_api.get_fleet_worker(
                project_id=self.project_id, fleet_id=fleet_id, name=worker_name
            )

            result = {
                "worker": worker,
                "profile": worker.status_details.profile if worker.status_details else None,
                "created_at": worker.created_at,
                "finished_at": worker.finished_at,
                "status": worker.status,
                "zone": worker.status_details.zone if worker.status_details else None,
                "address": worker.status_details.address if worker.status_details else None,
            }

            # Calculate duration if worker has finished
            if worker.created_at and worker.finished_at:
                duration = worker.finished_at - worker.created_at
                result["duration_seconds"] = duration.total_seconds()
            else:
                result["duration_seconds"] = None

            return result

        except ApiException as exc:
            print(
                "get_fleet_worker failed: project_id=%s fleet_id=%s worker_name=%s status=%s reason=%s",
                self.project_id,
                fleet_id,
                worker_name,
                getattr(exc, "status", None),
                getattr(exc, "reason", None),
            )
            raise

    def list_all_workers_consumption(  # pylint: disable=too-many-branches,too-many-statements,too-many-nested-blocks
        self,
        *,
        fleet_id: str,
        wait_for_completion: bool = True,
        timeout: int = 300,
        poll_interval: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Get resource consumption for all workers in a fleet.

        This is a blocking method that monitors workers during execution and captures
        their resource consumption data. It polls periodically and tracks the last known
        duration for each worker before they are deleted.

        Args:
            fleet_id: The ID of the fleet
            wait_for_completion: If True, wait for all workers to complete (default: True)
            timeout: Maximum time to wait in seconds (default: 300)
            poll_interval: Time between polling attempts in seconds (default: 5)

        Returns:
            List of dictionaries containing resource consumption data for each worker.
            Each dictionary contains:
            - worker_name: Name of the worker
            - profile: Worker profile (e.g., "cxf-2x4")
            - zone: Availability zone
            - created_at: Creation timestamp
            - finished_at: Completion timestamp (if available)
            - duration_seconds: Last known duration in seconds
            - status: Last known status
            - vcpu: Number of vCPUs (parsed from profile)
            - memory_gb: Memory in GB (parsed from profile)

        Raises:
            TimeoutError: If workers don't complete within the timeout period
            ApiException: If the API call fails

        Example:
            >>> handler = FleetHandler(client_provider=provider, project_id=project_id)
            >>> consumption_data = handler.list_all_workers_consumption(
            ...     fleet_id="fdb395e9-be32-43a8-9a42-6bd9a2e1623d",
            ...     wait_for_completion=True,
            ...     timeout=600
            ... )
            >>> for worker_data in consumption_data:
            ...     print(f"Worker: {worker_data['worker_name']}")
            ...     print(f"  Duration: {worker_data['duration_seconds']} seconds")
            ...     print(f"  vCPU: {worker_data['vcpu']}, Memory: {worker_data['memory_gb']} GB")
        """

        def parse_profile(profile: str) -> tuple[float, float]:
            """Parse worker profile to extract vCPU and memory."""
            if not profile or not profile.startswith("cxf-"):
                return (0.0, 0.0)

            parts = profile[4:].split("x")
            if len(parts) != 2:
                return (0.0, 0.0)

            try:
                vcpu = float(parts[0])
                memory_gb = float(parts[1])
                return (vcpu, memory_gb)
            except ValueError:
                return (0.0, 0.0)

        # Wait for workers to be created
        workers = self.wait_for_workers(fleet_id=fleet_id, timeout=60, poll_interval=poll_interval)

        # Initialize tracking for each worker
        worker_consumption = {}
        for worker in workers:
            worker_consumption[worker.name] = {
                "worker_name": worker.name,
                "profile": None,
                "zone": None,
                "created_at": None,
                "finished_at": None,
                "last_duration_seconds": 0.0,
                "status": "pending",
                "vcpu": 0.0,
                "memory_gb": 0.0,
            }

        if not wait_for_completion:
            # Just get current state and return
            for worker_name, tracked in worker_consumption.items():
                try:
                    consumption = self.get_worker_resource_consumption(
                        fleet_id=fleet_id, worker_name=worker_name
                    )
                    tracked["status"] = consumption["status"]
                    tracked["profile"] = consumption["profile"]
                    tracked["zone"] = consumption["zone"]
                    tracked["created_at"] = consumption["created_at"]
                    tracked["finished_at"] = consumption["finished_at"]
                    tracked["last_duration_seconds"] = consumption["duration_seconds"] or 0.0

                    if tracked["profile"]:
                        tracked["vcpu"], tracked["memory_gb"] = parse_profile(tracked["profile"])
                except ApiException:
                    pass  # Worker may have been deleted

            return list(worker_consumption.values())

        # Monitor workers until completion
        terminal_statuses = ["succeeded", "successful", "failed", "canceled", "stopped"]
        workers_seen = set()
        start_time = time.perf_counter()

        while True:
            elapsed_time = time.perf_counter() - start_time

            if elapsed_time >= timeout:
                raise TimeoutError(
                    f"Workers for fleet {fleet_id} did not complete within {timeout} seconds"
                )

            try:
                current_workers = self.list_workers(fleet_id=fleet_id)

                if current_workers:
                    current_worker_names = {w.name for w in current_workers}
                    workers_seen.update(current_worker_names)

                    # Update consumption for each worker
                    for worker in current_workers:
                        try:
                            consumption = self.get_worker_resource_consumption(
                                fleet_id=fleet_id, worker_name=worker.name
                            )

                            tracked = worker_consumption[worker.name]
                            tracked["status"] = consumption["status"]
                            tracked["profile"] = consumption["profile"] or tracked["profile"]
                            tracked["zone"] = consumption["zone"] or tracked["zone"]
                            tracked["created_at"] = (
                                consumption["created_at"] or tracked["created_at"]
                            )
                            tracked["finished_at"] = consumption["finished_at"]

                            # Update duration if available
                            if consumption["duration_seconds"] is not None:
                                tracked["last_duration_seconds"] = consumption["duration_seconds"]

                            # Parse profile to get vCPU and memory
                            if tracked["profile"] and tracked["vcpu"] == 0.0:
                                tracked["vcpu"], tracked["memory_gb"] = parse_profile(
                                    tracked["profile"]
                                )

                        except ApiException:
                            pass  # Worker may have been deleted

                    # Check if all workers have completed
                    workers_status = [w.status for w in current_workers]
                    all_completed = all(status in terminal_statuses for status in workers_status)

                    if all_completed:
                        break
                else:
                    # No workers found - they may have completed and been cleaned up
                    if workers_seen:
                        break

                time.sleep(poll_interval)

            except ApiException:
                # Workers may have been deleted, continue monitoring
                time.sleep(poll_interval)
                continue

        return list(worker_consumption.values())

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
        """
        Resolve a fleet identifier that may be either a UUID or a name into a fleet UUID.
        Args:
            identifier: name of the fleet or the fleet UUID

        Strategy:
          - If identifier looks like a UUID (8-4-4-4-12 pattern), return it directly.
          - Otherwise, list fleets and find one whose 'name' exactly matches.

        Raises:
            ValueError: if the name does not resolve to an existing fleet.
            ApiException: if the list call fails.
        """

        uuid_like = re.compile(
            r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
        )
        if uuid_like.match(identifier):
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
            if getattr(exc, "status", None) == 404:
                should_attempt_cancel = False
            else:
                should_attempt_cancel = True

        if should_attempt_cancel:
            try:
                self._fleets_api.cancel_fleet(project_id=self.project_id, id=fleet_id)
            except ApiException as exc:
                if getattr(exc, "status", None) != 404:
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
                if getattr(exc, "status", None) != 404:
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
            if getattr(exc, "status", None) != 404:
                raise

    def _wait_until_terminal_or_canceled(
        self,
        fleet_id: str,
        *,
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> None:
        """
        Poll the fleet until it reaches a terminal state (succeeded/successful/failed/canceled),
        or the fleet disappears (404), or we hit timeout.

        Raises:
            ApiException: If get_fleet fails with a non-404 error.
            AssertionError: If timeout is reached before observing a terminal/disappeared state.
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
                if getattr(exc, "status", None) == 404:
                    return
                raise

            if time.time() >= deadline:
                raise AssertionError(
                    f"Timed out waiting for fleet {fleet_id} to reach a terminal state."
                )
            time.sleep(poll_interval_seconds)
