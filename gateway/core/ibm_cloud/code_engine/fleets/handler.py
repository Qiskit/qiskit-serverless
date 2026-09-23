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

Configuration builders for volume mounts, environment variables, and
run commands are available as standalone functions in
:mod:`core.ibm_cloud.code_engine.fleets.utils`.

Example usage::

    handler = FleetHandler(
        client_provider=client_provider,
        project_id=project_id,
    )

    fleet = handler.submit_job(name="my-fleet", ...)
    handler.get_job_status(fleet.id)
    handler.cancel_job(fleet.id)
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from core.ibm_cloud.code_engine.ce_client import ApiClient
from core.ibm_cloud.code_engine.ce_client.api.fleets_api import FleetsApi
from core.ibm_cloud.code_engine.ce_client.rest import ApiException

logger = logging.getLogger("FleetHandler")

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

# Literal JSON key in the cancel_fleet body (a plain dict bypasses the model's attribute_map).
_CANCEL_PROCESSING_TASKS_KEY = "cancel_processing_tasks"

# Code Engine's error code for a cancel on a fleet it is already cancelling. Matched on the code
# rather than on the bare 409, so an unrelated conflict still surfaces instead of being read as
# "nothing to cancel".
_ALREADY_CANCELED_CODE = "fleet_already_canceled"

# How the generated models word their own validation failures, e.g.
# "Invalid value for `status` (standby), must be one of [...]". Used to tell a response body the
# model would not map from a ValueError raised before the request was ever sent. If the client is
# regenerated with different wording this stops matching, which fails safe: the cancel is reported
# as not delivered and retried, and the retry answers 409.
_MODEL_VALIDATION_ERROR = "Invalid value for"


def _is_already_canceled(exc: ApiException) -> bool:
    """Return True if an error body carries Code Engine's already-cancelling code.

    The status is not checked here. The caller pairs this with the 409 it applies to.
    """
    return _ALREADY_CANCELED_CODE in str(getattr(exc, "body", "") or "")


class FleetHandler:
    """Uses the swagger-generated FleetsAPI to manage fleet jobs."""

    def __init__(
        self,
        *,
        ce_api_client: ApiClient,
        project_id: str,
    ) -> None:
        """Initialize FleetHandler.

        Args:
            ce_api_client: Authenticated CE :class:`ApiClient`. Use
                :func:`~core.ibm_cloud.get_ce_auth` to create one.
            project_id: Code Engine project UUID.
        """
        self.project_id = project_id
        self._client = ce_api_client
        self._fleets_api = FleetsApi(ce_api_client)

    def submit_job(  # pylint: disable=too-many-arguments
        self,
        *,
        name: str,
        image_reference: str,
        network_placements: list[dict[str, Any]],
        scale_cpu_limit: str | None,
        scale_memory_limit: str | None,
        scale_max_instances: int,
        scale_retry_limit: int,
        tasks_specification: dict[str, Any],
        tasks_state_store: dict[str, Any],
        image_secret: str | None = None,
        extra_fields: dict[str, Any] | None = None,
    ) -> Any:
        """Submit a fleet job via POST /projects/{project_id}/fleets.

        Args:
            name: Fleet name (lowercase alphanumeric and hyphens).
            image_reference: Container image reference.
            network_placements: Network placement list, e.g.
                ``[{"type": "subnet_pool", "reference": "<id>"}]``.
            scale_cpu_limit: vCPUs per task, e.g. ``"1"``. Pass ``None`` when
                ``scale_preferred_worker_profile`` is set in ``extra_fields``.
            scale_memory_limit: Memory per task, e.g. ``"2G"``. Pass ``None``
                when ``scale_preferred_worker_profile`` is set.
            scale_max_instances: Tasks processed simultaneously (>= 1).
            scale_retry_limit: Times to retry a failed task (>= 0).
            tasks_specification: Task index spec, e.g. ``{"indices": "0"}``.
            tasks_state_store: Persistent data store, e.g.
                ``{"persistent_data_store": "<pds-name>"}``.
            image_secret: Registry pull secret name for private images.
            extra_fields: Additional valid FleetPrototype fields
                (e.g. ``run_commands``, ``scale_max_execution_time``).

        Returns:
            The fleet object returned by the swagger client.
        """
        body: dict[str, Any] = {
            "name": name,
            "image_reference": image_reference,
            "network_placements": network_placements,
            "scale_max_instances": scale_max_instances,
            "scale_retry_limit": scale_retry_limit,
            "tasks_specification": tasks_specification,
            "tasks_state_store": tasks_state_store,
        }
        if scale_cpu_limit is not None:
            body["scale_cpu_limit"] = scale_cpu_limit
        if scale_memory_limit is not None:
            body["scale_memory_limit"] = scale_memory_limit
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

        Known limitation: the generated ``V2Fleet`` validates ``status`` against a fixed list of
        eight values and raises ``ValueError`` for anything else. Code Engine returns ``standby``,
        which is not on that list, so this raises for such a fleet. ``cancel_job`` deliberately does
        not call this for that reason. Neither remaining caller is exposed to it:
        ``_get_fleet_name`` swallows every exception and has no callers of its own, and
        ``_wait_until_state`` is unreachable in production.

        Raises:
            ValueError: if identifier is a name and cannot be resolved, or if Code Engine reports a
                status the generated model does not know.
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
        wait: bool = False,
        delete: bool = False,
        cancel_processing_tasks: bool = True,
        timeout_seconds: int = 300,
        poll_interval_seconds: float = 2.0,
    ) -> bool:
        """
        Ask Code Engine to cancel a fleet ("job"), then optionally wait for terminal and delete.

        The fleet's status is deliberately not read first. Code Engine already answers whether a
        cancel was accepted, and reading the status beforehand made two things go wrong: a status
        the generated model does not recognise raised before we ever asked, and a rate-limited read
        silently skipped the cancel while the caller was told it had been sent.

        Steps:
        1) Resolve identifier (name or UUID) to a fleet UUID.
        2) Issue the cancel and interpret the response.
        3) If wait=True, poll until the fleet reaches a terminal state (or disappears).
        4) If delete=True, attempt to delete. Treat 404 as success.

        Args:
            identifier: Fleet UUID or fleet name.
            wait: If True, poll the fleet until terminal after the cancel. Defaults to False: the
                poller blocks for up to timeout_seconds and reads statuses through the generated
                model, neither of which belongs on a retry path.
            delete: If True, delete the fleet after optional wait.
            cancel_processing_tasks: If True, Code Engine kills the running task immediately
                instead of waiting for it to finish before completing the cancelation.
                Defaults to True so a cancel is honored even when the task never terminates
                on its own, which otherwise leaves the fleet stuck in "Canceling"
                indefinitely.
            timeout_seconds: Max time to wait for terminal state when wait=True.
            poll_interval_seconds: Delay between polls.

        Returns:
            ``True`` if Code Engine accepted the request, ``False`` if there was nothing left to
            cancel because the fleet is gone or a cancel is already in progress.

            ``True`` does not mean the fleet was doing anything. Code Engine answers 202 for a
            fleet whose task has already finished, and for one in ``standby``, both measured on
            staging. Deciding whether a cancel is worth sending belongs to the caller, which is
            what the scheduler will do once it holds the task-store state.

        Raises:
            ValueError: If identifier is a name that cannot be resolved, or if the cancel never
                left the process. A ValueError from the model refusing a 2xx body is swallowed
                instead, because that one means the cancel landed.
            ApiException: If the cancel could not be delivered, so the caller can retry. Also if
                delete_fleet fails with an error other than 404.
            AssertionError: If waiting is enabled and the fleet never reaches terminal before timeout.
        """
        fleet_id = self._resolve_fleet_id(identifier)
        cancel_sent = True

        try:
            self._fleets_api.cancel_fleet(
                project_id=self.project_id,
                id=fleet_id,
                body={_CANCEL_PROCESSING_TASKS_KEY: cancel_processing_tasks},
            )
        except ApiException as exc:
            # A non-2xx is raised by the transport before the body is deserialized into the model,
            # so a 404 or 409 here is Code Engine's own answer. The converse does not hold: parsing
            # a 2xx body can raise ApiException(status=0) too. 404 and an already-cancelling 409
            # mean there is nothing left to do; anything else, a 429 above all, means the cancel was
            # not delivered, so raise rather than claim it was.
            if exc.status == 404 or (exc.status == 409 and _is_already_canceled(exc)):
                logger.info("Fleet [%s] had nothing to cancel (HTTP %s)", fleet_id, exc.status)
                cancel_sent = False
            else:
                raise
        except ValueError as exc:
            # The generated model refuses a 2xx body it cannot map: a status outside its fixed list,
            # or a body too sparse for its required fields. Both read "Invalid value for `<field>`".
            # Only those mean the cancel landed, because a non-2xx raises ApiException above.
            #
            # Every other ValueError means the request never left the process, and reporting one as
            # a delivered cancel would be the exact bug this method was changed to remove. Two are
            # reachable: the generated client's own missing-parameter check, and urllib3's
            # LocationValueError / LocationParseError, which are ValueError subclasses.
            if _MODEL_VALIDATION_ERROR not in str(exc):
                raise
            logger.info("Fleet [%s] cancel accepted, response body not parseable", fleet_id)

        # Optionally wait for terminal to avoid delete races.
        if wait:
            self._wait_until_terminal_or_canceled(
                fleet_id,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )

        # Optionally delete; fleet_id is already resolved so pass it directly.
        if delete:
            self.delete_job(fleet_id)

        return cancel_sent

    def delete_job(self, identifier: str) -> None:
        """
        Delete a fleet ("job") by name or UUID without attempting a cancel.

        Args:
            identifier: Fleet UUID or fleet name.

        Raises:
            ValueError: If identifier is a name that cannot be resolved.
            ApiException: If delete_fleet fails with an error other than 404 or 429.
        """
        fleet_id = self._resolve_fleet_id(identifier)
        while True:
            try:
                self._fleets_api.delete_fleet(project_id=self.project_id, id=fleet_id)
                return
            except ApiException as exc:
                if exc.status == 404:
                    return
                if exc.status == 429:
                    logger.warning("Rate limited deleting fleet %s — backing off 60s", fleet_id)
                    time.sleep(60.0)
                    continue
                raise

    def _wait_until_state(
        self,
        fleet_id: str,
        *,
        target_states: set[str],
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> str:
        """Poll the fleet until its status is in ``target_states``, it disappears, or timeout.

        On a 429 response the sleep is extended to ``poll_interval_seconds * 6``
        to let the CE rate limit window recover, then polling resumes normally.

        Known CE fleet statuses::

            pending, running, canceling, canceled, deleting, failed,
            succeeded, successful

        That list is incomplete: Code Engine also returns ``standby``, which the generated model
        rejects, so ``get_job_status`` raises ``ValueError`` for such a fleet and this loop, which
        catches only ``ApiException``, would not survive it. Unreachable in production, because the
        only caller is ``cancel_job(wait=True)`` and nothing passes that.

        Args:
            fleet_id: Fleet UUID to poll.
            target_states: Set of lowercase status strings that end the poll.
            timeout_seconds: Maximum seconds to wait before raising.
            poll_interval_seconds: Seconds between each status check.

        Returns:
            The status string that satisfied ``target_states``, or ``"gone"``
            if the fleet disappeared with a 404 before reaching a target state.

        Raises:
            ApiException: If get_fleet fails with a non-404/non-429 error.
            AssertionError: If timeout is reached before a target state is observed.
        """
        deadline = time.time() + timeout_seconds

        while True:
            try:
                info = self.get_job_status(fleet_id)
                status = (info.get("status") or "").lower()
                if status in target_states:
                    return status
            except ApiException as exc:
                if exc.status == 404:
                    return "gone"
                if exc.status == 429:
                    backoff = poll_interval_seconds * 6
                    logger.warning(
                        "Rate limited polling fleet %s — backing off %.0fs",
                        fleet_id,
                        backoff,
                    )
                    time.sleep(backoff)
                    continue
                raise

            if time.time() >= deadline:
                raise AssertionError(f"Timed out waiting for fleet {fleet_id} to reach one of {target_states}.")
            time.sleep(poll_interval_seconds)

    def _wait_until_terminal_or_canceled(
        self,
        fleet_id: str,
        *,
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> None:
        """Poll the fleet until it reaches a terminal state or disappears.

        Delegates to :meth:`_wait_until_state` with the full set of CE terminal
        statuses: ``succeeded``, ``successful``, ``failed``, ``canceled``.

        Args:
            fleet_id: Fleet UUID to poll.
            timeout_seconds: Maximum seconds to wait before raising.
            poll_interval_seconds: Seconds between each status check.

        Raises:
            ApiException: If get_fleet fails with a non-404/non-429 error.
            AssertionError: If timeout is reached before a terminal state is observed.
        """
        self._wait_until_state(
            fleet_id,
            target_states={"succeeded", "successful", "failed", "canceled"},
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
