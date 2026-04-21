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
Worker lifecycle sub-manager for :class:`FleetHandler`.

Provides methods for listing, waiting on, and monitoring resource
consumption of fleet workers.

This module is not imported directly. Access it via the parent handler::

    handler = FleetHandler(client_provider=provider, project_id=project_id)
    workers = handler.workers.list(fleet_id="...")
    handler.workers.wait(fleet_id="...", timeout=120)
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast

from swagger_client.rest import ApiException

if TYPE_CHECKING:
    from .fleet_handler import FleetHandler


def _parse_profile(profile: str) -> tuple[float, float]:
    """Parse worker profile string (e.g. ``"cxf-2x4"``) to extract vCPU and memory GB."""
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


class JobWorkers:
    """
    Sub-manager for fleet worker operations.

    Instances are created automatically by :class:`FleetHandler` and
    should not be instantiated directly.
    """

    def __init__(self, job: FleetHandler) -> None:
        self._job = job

    @property
    def _project_id(self) -> str:
        return self._job.project_id

    @property
    def _fleets_api(self) -> Any:
        return self._job._fleets_api  # pylint: disable=protected-access

    def list(self, *, fleet_id: str) -> list[Any]:
        """
        List all workers for a given fleet.

        Args:
            fleet_id: The ID of the fleet.

        Returns:
            List of worker objects from the API.

        Raises:
            ApiException: If the API call fails.

        Example:
            >>> workers = handler.workers.list(fleet_id="fdb395e9-...")
            >>> for worker in workers:
            ...     print(f"Worker: {worker.name}, Status: {worker.status}")
        """
        try:
            workers_response = self._fleets_api.list_fleet_workers(
                project_id=self._project_id, fleet_id=fleet_id
            )
            if workers_response is None or not hasattr(workers_response, "workers"):
                return []

            return cast(Any, workers_response).workers or []

        except ApiException as exc:
            print(
                "list_fleet_workers failed: project_id=%s fleet_id=%s status=%s reason=%s",
                self._project_id,
                fleet_id,
                getattr(exc, "status", None),
                getattr(exc, "reason", None),
            )
            raise

    def wait(self, *, fleet_id: str, timeout: int = 60, poll_interval: int = 5) -> list[Any]:
        """
        Wait for workers to be created for a fleet, with timeout and polling.

        Polls the fleet workers API until at least one worker is found,
        or until the timeout is reached.

        Args:
            fleet_id: The ID of the fleet.
            timeout: Maximum time to wait in seconds (default: 60).
            poll_interval: Time between polling attempts in seconds (default: 5).

        Returns:
            List of worker objects once found.

        Raises:
            TimeoutError: If no workers are found within the timeout period.
            ApiException: If the API call fails with a non-404 error.

        Example:
            >>> workers = handler.workers.wait(
            ...     fleet_id="fdb395e9-...", timeout=120, poll_interval=3
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
                workers = self.list(fleet_id=fleet_id)

                if workers:
                    return workers

                time.sleep(poll_interval)

            except ApiException as exc:
                # If it's a 404, the fleet might not be ready yet
                if exc.status == 404:
                    time.sleep(poll_interval)
                    continue
                raise

    def get_resource_consumption(
        self,
        *,
        fleet_id: str,
        worker_name: str,
    ) -> dict[str, Any]:
        """
        Get resource consumption details for a specific fleet worker.

        Retrieves worker information including vCPU, memory, GPU allocation,
        and duration based on ``created_at`` / ``finished_at`` timestamps.

        Args:
            fleet_id: The ID of the fleet.
            worker_name: The name of the worker.

        Returns:
            Dictionary containing worker, profile, created_at, finished_at,
            duration_seconds, status, zone, and address.

        Example:
            >>> consumption = handler.workers.get_resource_consumption(
            ...     fleet_id="fdb395e9-...", worker_name="fleet-...-0"
            ... )
            >>> print(f"Profile: {consumption['profile']}")
        """
        try:
            worker = self._fleets_api.get_fleet_worker(
                project_id=self._project_id, fleet_id=fleet_id, name=worker_name
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
                self._project_id,
                fleet_id,
                worker_name,
                getattr(exc, "status", None),
                getattr(exc, "reason", None),
            )
            raise

    def list_all_consumption(  # pylint: disable=too-many-branches,too-many-statements,too-many-nested-blocks
        self,
        *,
        fleet_id: str,
        wait_for_completion: bool = True,
        timeout: int = 300,
        poll_interval: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Get resource consumption for all workers in a fleet.

        This is a blocking method that monitors workers during execution and
        captures their resource consumption data. It polls periodically and
        tracks the last known duration for each worker before they are deleted.

        Args:
            fleet_id: The ID of the fleet.
            wait_for_completion: If True, wait for all workers to complete.
            timeout: Maximum time to wait in seconds (default: 300).
            poll_interval: Time between polling attempts in seconds (default: 5).

        Returns:
            List of dictionaries containing resource consumption data for
            each worker including worker_name, profile, zone, created_at,
            finished_at, duration_seconds, status, vcpu, and memory_gb.

        Raises:
            TimeoutError: If workers don't complete within the timeout period.
            ApiException: If the API call fails.

        Example:
            >>> data = handler.workers.list_all_consumption(
            ...     fleet_id="fdb395e9-...", wait_for_completion=True, timeout=600
            ... )
            >>> for w in data:
            ...     print(f"Worker: {w['worker_name']}, vCPU: {w['vcpu']}")
        """
        # Wait for workers to be created
        workers = self.wait(fleet_id=fleet_id, timeout=60, poll_interval=poll_interval)

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
                    consumption = self.get_resource_consumption(
                        fleet_id=fleet_id, worker_name=worker_name
                    )
                    tracked["status"] = consumption["status"]
                    tracked["profile"] = consumption["profile"]
                    tracked["zone"] = consumption["zone"]
                    tracked["created_at"] = consumption["created_at"]
                    tracked["finished_at"] = consumption["finished_at"]
                    tracked["last_duration_seconds"] = consumption["duration_seconds"] or 0.0

                    if tracked["profile"]:
                        tracked["vcpu"], tracked["memory_gb"] = _parse_profile(tracked["profile"])
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
                current_workers = self.list(fleet_id=fleet_id)

                if current_workers:
                    current_worker_names = {w.name for w in current_workers}
                    workers_seen.update(current_worker_names)

                    # Update consumption for each worker
                    for worker in current_workers:
                        try:
                            consumption = self.get_resource_consumption(
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
                                tracked["vcpu"], tracked["memory_gb"] = _parse_profile(
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
