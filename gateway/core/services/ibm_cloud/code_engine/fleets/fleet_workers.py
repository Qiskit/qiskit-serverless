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

Provides methods for listing, waiting on, and tracking resource allocation
of fleet workers. Allocation data is derived from the CE API (profile,
created_at/finished_at). Actual utilization metrics are out of scope here
and will be provided by Sysdig in a future integration.

This module is not imported directly. Access it via the parent handler::

    handler = FleetHandler(client_provider=provider, project_id=project_id)

    # List workers currently running in a fleet
    workers = handler.workers.list(fleet_id="fdb395e9-...")

    # Wait until at least one worker is created
    workers = handler.workers.wait(fleet_id="fdb395e9-...", timeout=120)

    # Get allocated profile and timing for a single worker
    allocation = handler.workers.get_worker_resource_allocation(
        fleet_id="fdb395e9-...",
        worker_name="fleet-fdb395e9-...-0",
    )
    print(f"Profile: {allocation['profile']}, duration: {allocation['duration_seconds']}s")

    # Collect allocation data for all workers, waiting for completion
    allocations = handler.workers.list_all_allocations(
        fleet_id="fdb395e9-...",
        wait_for_completion=True,
        timeout=600,
    )
    for w in allocations:
        print(f"{w['worker_name']}: {w['vcpu']} vCPU, {w['memory_gb']} GB, {w['last_duration_seconds']}s")
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from swagger_client.rest import ApiException

if TYPE_CHECKING:
    from core.services.ibm_cloud.code_engine.fleets.fleet_handler import FleetHandler

logger = logging.getLogger("FleetHandler")


def _parse_profile(profile: str) -> tuple[float, float]:
    """Parse worker profile string to extract vCPU and memory GB.

    Args:
        profile: Profile string in ``"cxf-<vcpu>x<memory>"`` format, e.g. ``"cxf-2x4"``.

    Returns:
        Tuple of ``(vcpu, memory_gb)``. Returns ``(0.0, 0.0)`` for unrecognised formats.
    """
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


def _empty_allocation(worker_name: str) -> dict[str, Any]:
    """Return a zeroed allocation dict for a worker not yet observed.

    Args:
        worker_name: CE worker name.

    Returns:
        Allocation dict with all numeric fields at zero and status ``"pending"``.
    """
    return {
        "worker_name": worker_name,
        "profile": None,
        "zone": None,
        "created_at": None,
        "finished_at": None,
        "last_duration_seconds": 0.0,
        "status": "pending",
        "vcpu": 0.0,
        "memory_gb": 0.0,
    }


class JobWorkers:
    """
    Sub-manager for fleet worker operations.

    Instances are created automatically by :class:`FleetHandler` and
    should not be instantiated directly.
    """

    def __init__(self, job: FleetHandler) -> None:
        self._job = job

    def list(self, *, fleet_id: str) -> list[Any]:
        """List all workers for a given fleet.

        Args:
            fleet_id: The ID of the fleet.

        Returns:
            List of worker objects from the API.

        Raises:
            ApiException: If the API call fails.
        """
        try:
            workers_response = self._job._fleets_api.list_fleet_workers(  # pylint: disable=protected-access
                project_id=self._job.project_id, fleet_id=fleet_id
            )
            if workers_response is None or not hasattr(workers_response, "workers"):
                return []
            return workers_response.workers or []

        except ApiException as exc:
            logger.error(
                "list_fleet_workers failed: project_id=%s fleet_id=%s status=%s reason=%s",
                self._job.project_id,
                fleet_id,
                exc.status,
                exc.reason,
            )
            raise

    def wait(self, *, fleet_id: str, timeout: int = 60, poll_interval: int = 5) -> list[Any]:
        """Wait for workers to be created for a fleet, with timeout and polling.

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
        """
        start_time = time.perf_counter()

        while True:
            if time.perf_counter() - start_time >= timeout:
                raise TimeoutError(f"No workers were created for fleet {fleet_id} after waiting {timeout} seconds")

            try:
                workers = self.list(fleet_id=fleet_id)
                if workers:
                    return workers
                time.sleep(poll_interval)

            except ApiException as exc:
                if exc.status == 404:
                    time.sleep(poll_interval)
                    continue
                raise

    def get_worker_resource_allocation(
        self,
        *,
        fleet_id: str,
        worker_name: str,
    ) -> dict[str, Any]:
        """Get resource allocation details for a specific fleet worker.

        Returns the allocated profile and timing data reported by the CE API.
        This reflects what was *allocated* to the worker (profile, zone,
        created_at/finished_at), not actual CPU/memory utilization — that will
        be provided by Sysdig in a future integration.

        Args:
            fleet_id: The ID of the fleet.
            worker_name: The name of the worker.

        Returns:
            Dictionary with keys: worker, profile, created_at, finished_at,
            duration_seconds (None if not finished), status, zone, address.

        Raises:
            ApiException: If the API call fails.
        """
        try:
            worker = self._job._fleets_api.get_fleet_worker(  # pylint: disable=protected-access
                project_id=self._job.project_id, fleet_id=fleet_id, name=worker_name
            )

            details = worker.status_details
            duration_seconds: float | None = None
            if worker.created_at and worker.finished_at:
                duration_seconds = (worker.finished_at - worker.created_at).total_seconds()

            return {
                "worker": worker,
                "profile": details.profile if details else None,
                "created_at": worker.created_at,
                "finished_at": worker.finished_at,
                "duration_seconds": duration_seconds,
                "status": worker.status,
                "zone": details.zone if details else None,
                "address": details.address if details else None,
            }

        except ApiException as exc:
            logger.error(
                "get_fleet_worker failed: project_id=%s fleet_id=%s worker_name=%s status=%s reason=%s",
                self._job.project_id,
                fleet_id,
                worker_name,
                exc.status,
                exc.reason,
            )
            raise

    def list_all_allocations(  # pylint: disable=too-many-branches,too-many-statements,too-many-nested-blocks
        self,
        *,
        fleet_id: str,
        wait_for_completion: bool = True,
        timeout: int = 300,
        poll_interval: int = 5,
    ) -> list[dict[str, Any]]:
        """Collect resource allocation data for all workers in a fleet.

        Polls the CE API for worker status and profile information. Returns
        allocated profile, parsed vCPU/memory, and timing data per worker.
        Actual utilization metrics are out of scope — those will be provided
        by Sysdig in a future integration.

        Args:
            fleet_id: The ID of the fleet.
            wait_for_completion: If True, poll until all workers reach a
                terminal state before returning.
            timeout: Maximum time to wait in seconds (default: 300).
            poll_interval: Time between polling attempts in seconds (default: 5).

        Returns:
            List of per-worker allocation dicts with keys: worker_name, profile,
            zone, created_at, finished_at, last_duration_seconds, status,
            vcpu, memory_gb.

        Raises:
            TimeoutError: If workers don't reach terminal state within timeout.
            ApiException: If the API call fails.
        """
        initial_workers = self.wait(fleet_id=fleet_id, timeout=60, poll_interval=poll_interval)

        worker_allocations: dict[str, dict[str, Any]] = {w.name: _empty_allocation(w.name) for w in initial_workers}

        if not wait_for_completion:
            for worker_name, tracked in worker_allocations.items():
                try:
                    allocation = self.get_worker_resource_allocation(fleet_id=fleet_id, worker_name=worker_name)
                    _update_tracked(tracked, allocation)
                except ApiException:
                    pass  # worker may have been deleted between list and get
            return list(worker_allocations.values())

        terminal_statuses = {"succeeded", "successful", "failed", "canceled"}
        workers_seen: set[str] = set()
        start_time = time.perf_counter()

        while True:
            if time.perf_counter() - start_time >= timeout:
                raise TimeoutError(f"Workers for fleet {fleet_id} did not complete within {timeout} seconds")

            try:
                current_workers = self.list(fleet_id=fleet_id)

                if current_workers:
                    workers_seen.update(w.name for w in current_workers)

                    for worker in current_workers:
                        if worker.name not in worker_allocations:
                            worker_allocations[worker.name] = _empty_allocation(worker.name)
                        try:
                            allocation = self.get_worker_resource_allocation(fleet_id=fleet_id, worker_name=worker.name)
                            _update_tracked(worker_allocations[worker.name], allocation)
                        except ApiException:
                            pass  # worker may have been deleted between list and get

                    if all(w.status in terminal_statuses for w in current_workers):
                        break

                elif workers_seen:
                    break  # all workers completed and were cleaned up

                time.sleep(poll_interval)

            except ApiException as exc:
                logger.warning(
                    "list_fleet_workers transient error for fleet %s: status=%s — retrying",
                    fleet_id,
                    exc.status,
                )
                time.sleep(poll_interval)
                continue

        return list(worker_allocations.values())


def _update_tracked(tracked: dict[str, Any], allocation: dict[str, Any]) -> None:
    """Merge a fresh allocation snapshot into a tracked worker dict.

    Args:
        tracked: Mutable worker allocation dict to update in-place.
        allocation: Fresh result from :meth:`JobWorkers.get_worker_resource_allocation`.
    """
    tracked["status"] = allocation["status"]
    tracked["profile"] = allocation["profile"] or tracked["profile"]
    tracked["zone"] = allocation["zone"] or tracked["zone"]
    tracked["created_at"] = allocation["created_at"] or tracked["created_at"]
    tracked["finished_at"] = allocation["finished_at"]
    if allocation["duration_seconds"] is not None:
        tracked["last_duration_seconds"] = allocation["duration_seconds"]
    if tracked["profile"] and tracked["vcpu"] == 0.0:
        tracked["vcpu"], tracked["memory_gb"] = _parse_profile(tracked["profile"])
