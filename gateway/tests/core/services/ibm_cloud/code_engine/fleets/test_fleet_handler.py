# This code is part of a Qiskit project.
#
# (C) IBM 2026
#
# This code is licensed under the Apache License, Version 2.0.
# You may obtain a copy of this license in the LICENSE.txt file
# in the root directory of this source tree or at
# http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""
Unit tests for FleetHandler and fleet_utils builder functions.

COS sub-manager tests live in test_job_cos_unit.py.
Worker sub-manager tests are exercised via handler.workers.* below.
"""

# pylint: disable=redefined-outer-name

import logging
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from swagger_client.rest import ApiException

from core.services.ibm_cloud.code_engine.fleets.fleet_handler import FleetHandler
from core.services.ibm_cloud.code_engine.fleets.fleet_utils import (
    build_run_commands,
    build_run_env_variables,
    build_run_volume_mounts,
)

_HANDLER_MOD = "core.services.ibm_cloud.code_engine.fleets.fleet_handler"


@pytest.fixture
def mock_provider():
    """Return a minimal IBMCloudClientProvider mock with config and auth wired up."""
    provider = MagicMock()
    provider.config.code_engine_url = "https://codeengine.test.cloud.ibm.com/v2"
    provider.config.region = "us-south"
    provider.auth.token = "TEST_TOKEN"
    return provider


@pytest.fixture
def project_id():
    """Return a fake Code Engine project UUID."""
    return "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def base_payload():
    """Return a minimal valid payload for submit_job calls."""
    return {
        "name": "fleet-1",
        "image_reference": "icr.io/codeengine/helloworld",
        "network_placements": [{"type": "subnet_pool", "reference": "abc-123"}],
        "scale_cpu_limit": "1",
        "scale_memory_limit": "2G",
        "scale_max_instances": 1,
        "scale_retry_limit": 0,
        "tasks_specification": {"indices": "0"},
        "tasks_state_store": {"persistent_data_store": "fleet-task-store"},
    }


def _make_handler(
    mock_provider: MagicMock,
    project_id: str,
    mock_api_client_cls: MagicMock,
    mock_fleets_api_cls: MagicMock,
) -> tuple[FleetHandler, MagicMock]:
    """Construct a FleetHandler wired to mock API classes.

    Args:
        mock_provider: Mock IBMCloudClientProvider.
        project_id: Code Engine project UUID string.
        mock_api_client_cls: Patched ApiClient class.
        mock_fleets_api_cls: Patched FleetsApi class.

    Returns:
        Tuple of ``(handler, mock_fleets_api_instance)``.
    """
    mock_api_client_cls.return_value = MagicMock()
    mock_fleets_api = MagicMock()
    mock_fleets_api_cls.return_value = mock_fleets_api
    handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
    return handler, mock_fleets_api


def _expected_body(
    base_payload: dict,
    image_secret: str | None = None,
    extra_fields: dict | None = None,
) -> dict:
    """Build the expected create_fleet body from a base payload and optional overrides.

    Args:
        base_payload: Mandatory submit_job fields.
        image_secret: Optional registry secret name to include.
        extra_fields: Optional additional fields to merge.

    Returns:
        Dict representing the expected request body.
    """
    body = dict(base_payload)
    if image_secret:
        body["image_secret"] = image_secret
    if extra_fields:
        body.update(extra_fields)
    return body


@patch(f"{_HANDLER_MOD}.FleetsApi")
@patch(f"{_HANDLER_MOD}.ApiClient")
def test_submit_job_happy_path(
    mock_api_client_cls, mock_fleets_api_cls, mock_provider, project_id, base_payload
):
    """submit_job passes the correct body and project_id to create_fleet and returns its result."""
    handler, mock_fleets_api = _make_handler(
        mock_provider, project_id, mock_api_client_cls, mock_fleets_api_cls
    )
    created_resp = {"id": "fleet-id-123", "name": base_payload["name"]}
    mock_fleets_api.create_fleet.return_value = created_resp

    result = handler.submit_job(**base_payload)

    assert result == created_resp
    mock_fleets_api.create_fleet.assert_called_once()
    call_kwargs = mock_fleets_api.create_fleet.call_args.kwargs
    assert call_kwargs["project_id"] == project_id
    assert call_kwargs["body"] == _expected_body(base_payload)


@patch(f"{_HANDLER_MOD}.FleetsApi")
@patch(f"{_HANDLER_MOD}.ApiClient")
def test_submit_job_with_optional_fields(
    mock_api_client_cls, mock_fleets_api_cls, mock_provider, project_id, base_payload
):
    """submit_job adds image_secret and merges extra_fields into the request body."""
    handler, mock_fleets_api = _make_handler(
        mock_provider, project_id, mock_api_client_cls, mock_fleets_api_cls
    )
    extra = {
        "command": ["/bin/sh", "-lc", "echo hello"],
        "args": ["--foo", "bar"],
        "scale_max_execution_time": 600,
    }
    image_secret = "cr-secret-1"

    handler.submit_job(**base_payload, image_secret=image_secret, extra_fields=extra)

    call_kwargs = mock_fleets_api.create_fleet.call_args.kwargs
    assert call_kwargs["body"] == _expected_body(
        base_payload, image_secret=image_secret, extra_fields=extra
    )


@patch(f"{_HANDLER_MOD}.FleetsApi")
@patch(f"{_HANDLER_MOD}.ApiClient")
def test_submit_job_raises_and_logs_api_exception(
    mock_api_client_cls, mock_fleets_api_cls, mock_provider, project_id, base_payload, caplog
):
    """submit_job logs an error and re-raises on ApiException."""
    handler, mock_fleets_api = _make_handler(
        mock_provider, project_id, mock_api_client_cls, mock_fleets_api_cls
    )
    mock_fleets_api.create_fleet.side_effect = ApiException(status=403, reason="Forbidden")

    with caplog.at_level(logging.ERROR, logger="FleetHandler"):
        with pytest.raises(ApiException):
            handler.submit_job(**base_payload)

    assert "create_fleet failed" in caplog.text
    assert str(project_id) in caplog.text
    assert "403" in caplog.text
    assert "Forbidden" in caplog.text


@patch(f"{_HANDLER_MOD}.FleetsApi")
@patch(f"{_HANDLER_MOD}.ApiClient")
def test_fleet_handler_initializes_api_clients_with_provider_config(
    mock_api_client_cls, mock_fleets_api_cls, mock_provider, project_id, base_payload
):
    """FleetHandler sets host and Authorization bearer token from the provider."""
    seen_cfg: dict = {}

    def _capture_cfg(cfg):
        """Capture Configuration fields passed to ApiClient constructor."""
        seen_cfg["host"] = getattr(cfg, "host", None)
        seen_cfg["api_key"] = dict(getattr(cfg, "api_key", {}))
        seen_cfg["api_key_prefix"] = dict(getattr(cfg, "api_key_prefix", {}))
        return MagicMock()

    mock_api_client_cls.side_effect = _capture_cfg
    mock_fleets_api_cls.return_value = MagicMock()

    handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
    handler.submit_job(**base_payload)

    assert seen_cfg["host"] == mock_provider.config.code_engine_url
    assert seen_cfg["api_key"].get("Authorization") == mock_provider.auth.token
    assert seen_cfg["api_key_prefix"].get("Authorization") == "Bearer"


@patch(f"{_HANDLER_MOD}.FleetsApi")
@patch(f"{_HANDLER_MOD}.ApiClient")
def test_submit_job_with_builder_extra_fields(
    mock_api_client_cls, mock_fleets_api_cls, mock_provider, project_id, base_payload
):
    """submit_job accepts extra_fields built from fleet_utils builder functions."""
    handler, mock_fleets_api = _make_handler(
        mock_provider, project_id, mock_api_client_cls, mock_fleets_api_cls
    )
    mock_fleets_api.create_fleet.return_value = {"id": "fleet-id-123"}

    extra_fields = {
        "run_volume_mounts": build_run_volume_mounts(
            mounts=[("/output", "test-pds", "test_user/fleet-1")]
        ),
        "run_env_variables": build_run_env_variables(primary_mount_path="/output"),
        "run_commands": build_run_commands(app_run_commands=["python", "main.py"]),
    }

    handler.submit_job(**base_payload, extra_fields=extra_fields)

    body = mock_fleets_api.create_fleet.call_args.kwargs["body"]
    mount = body["run_volume_mounts"][0]
    assert mount["mount_path"] == "/output"
    assert mount["reference"] == "test-pds"
    assert mount["type"] == "persistent_data_store"
    assert mount["sub_path"] == "test_user/fleet-1"
    assert body["run_commands"][0] == "sh"
    assert body["run_commands"][1] == "-c"
    assert "mkdir -p" in body["run_commands"][2]


def test_get_job_status_uuid_happy_path(mock_provider, project_id):
    """get_job_status returns the expected summary dict for a UUID identifier."""
    fleet_uuid = "4db7db50-1b3f-4b53-98f0-f7ad0ee96280"
    payload = {
        "id": fleet_uuid,
        "name": "test-fleet",
        "status": "running",
        "scale_max_instances": 3,
        "running_instances": 2,
        "created_at": "2026-02-17T01:23:45Z",
        "updated_at": "2026-02-17T01:55:00Z",
    }

    with (
        patch(f"{_HANDLER_MOD}.ApiClient") as mock_api_client_cls,
        patch(f"{_HANDLER_MOD}.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        model_obj = MagicMock()
        model_obj.to_dict.return_value = payload
        fleets_api = MagicMock()
        fleets_api.get_fleet.return_value = model_obj
        mock_fleets_api_cls.return_value = fleets_api

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        with patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid):
            result = handler.get_job_status(fleet_uuid)

    assert result == {
        "id": fleet_uuid,
        "name": "test-fleet",
        "status": "running",
        "desired_instances": 3,
        "running_instances": 2,
        "created_at": "2026-02-17T01:23:45Z",
        "updated_at": "2026-02-17T01:55:00Z",
        "raw": payload,
    }
    fleets_api.get_fleet.assert_called_once_with(project_id=project_id, id=fleet_uuid)


def test_get_job_status_name_happy_path(mock_provider, project_id):
    """get_job_status handles fallback fields (state/created/updated) for name identifiers."""
    fleet_name = "test-fleet"
    fleet_uuid = "4db7db50-1b3f-4b53-98f0-f7ad0ee96280"
    payload = {
        "id": fleet_uuid,
        "name": fleet_name,
        "state": "succeeded",
        "desired_instances": 1,
        "running_instances": 0,
        "created": "2026-02-18T10:00:00Z",
        "updated": "2026-02-18T10:05:00Z",
    }

    with (
        patch(f"{_HANDLER_MOD}.ApiClient") as mock_api_client_cls,
        patch(f"{_HANDLER_MOD}.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        fleets_api.get_fleet.return_value = payload  # plain dict, no to_dict
        mock_fleets_api_cls.return_value = fleets_api

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        with patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid):
            result = handler.get_job_status(fleet_name)

    assert result["status"] == "succeeded"
    assert result["created_at"] == "2026-02-18T10:00:00Z"
    assert result["updated_at"] == "2026-02-18T10:05:00Z"
    assert result["raw"] == payload


def test_get_job_status_name_not_found_raises_value_error(mock_provider, project_id):
    """get_job_status propagates ValueError when name resolution fails."""
    with (
        patch(f"{_HANDLER_MOD}.ApiClient") as mock_api_client_cls,
        patch(f"{_HANDLER_MOD}.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        mock_fleets_api_cls.return_value = MagicMock()

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        with patch.object(handler, "_resolve_fleet_id", side_effect=ValueError("Fleet not found")):
            with pytest.raises(ValueError, match="not.*found|Fleet not found"):
                handler.get_job_status("does-not-exist")


def test_get_job_status_api_exception(mock_provider, project_id):
    """get_job_status propagates ApiException from get_fleet."""
    with (
        patch(f"{_HANDLER_MOD}.ApiClient") as mock_api_client_cls,
        patch(f"{_HANDLER_MOD}.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        fleets_api.get_fleet.side_effect = ApiException(status=404, reason="Not Found")
        mock_fleets_api_cls.return_value = fleets_api

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        fleet_uuid = "4db7db50-1b3f-4b53-98f0-f7ad0ee96280"
        with patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid):
            with pytest.raises(ApiException) as exc:
                handler.get_job_status(fleet_uuid)
        assert exc.value.status == 404


def test_cancel_job_happy_path_waits_no_delete_by_default(mock_provider, project_id):
    """cancel_job cancels a running fleet, waits, and does not delete by default."""
    with (
        patch(f"{_HANDLER_MOD}.ApiClient") as mock_api_client_cls,
        patch(f"{_HANDLER_MOD}.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        mock_fleets_api_cls.return_value = fleets_api
        fleet_uuid = "f-00000000-0000-0000-0000-000000000001"

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        with (
            patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid),
            patch.object(handler, "_wait_until_terminal_or_canceled") as waiter,
            patch.object(handler, "get_job_status", return_value={"status": "running"}),
        ):
            handler.cancel_job(fleet_uuid, wait=True, timeout_seconds=10, poll_interval_seconds=0.01)

    fleets_api.cancel_fleet.assert_called_once_with(project_id=project_id, id=fleet_uuid)
    waiter.assert_called_once()
    fleets_api.delete_fleet.assert_not_called()


def test_cancel_job_waits_and_deletes_when_flag_set(mock_provider, project_id):
    """cancel_job with delete=True deletes after waiting."""
    with (
        patch(f"{_HANDLER_MOD}.ApiClient") as mock_api_client_cls,
        patch(f"{_HANDLER_MOD}.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        mock_fleets_api_cls.return_value = fleets_api
        fleet_uuid = "f-00000000-0000-0000-0000-000000000002"

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        with (
            patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid),
            patch.object(handler, "_wait_until_terminal_or_canceled") as waiter,
            patch.object(handler, "get_job_status", return_value={"status": "pending"}),
        ):
            handler.cancel_job(fleet_uuid, wait=True, delete=True)

    fleets_api.cancel_fleet.assert_called_once_with(project_id=project_id, id=fleet_uuid)
    waiter.assert_called_once()
    fleets_api.delete_fleet.assert_called_once_with(project_id=project_id, id=fleet_uuid)


def test_cancel_job_no_wait_skips_poller(mock_provider, project_id):
    """cancel_job with wait=False calls cancel but not the poller."""
    with (
        patch(f"{_HANDLER_MOD}.ApiClient") as mock_api_client_cls,
        patch(f"{_HANDLER_MOD}.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        mock_fleets_api_cls.return_value = fleets_api
        fleet_uuid = "f-00000000-0000-0000-0000-000000000003"

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        with (
            patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid),
            patch.object(handler, "_wait_until_terminal_or_canceled") as waiter,
            patch.object(handler, "get_job_status", return_value={"status": "running"}),
        ):
            handler.cancel_job(fleet_uuid, wait=False)

    fleets_api.cancel_fleet.assert_called_once_with(project_id=project_id, id=fleet_uuid)
    waiter.assert_not_called()
    fleets_api.delete_fleet.assert_not_called()


def test_cancel_job_ignores_404_on_cancel(mock_provider, project_id):
    """cancel_job treats 404 from cancel_fleet as already gone and continues."""
    with (
        patch(f"{_HANDLER_MOD}.ApiClient") as mock_api_client_cls,
        patch(f"{_HANDLER_MOD}.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        fleets_api.cancel_fleet.side_effect = ApiException(status=404, reason="Not Found")
        mock_fleets_api_cls.return_value = fleets_api
        fleet_uuid = "f-00000000-0000-0000-0000-000000000004"

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        with (
            patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid),
            patch.object(handler, "_wait_until_terminal_or_canceled") as waiter,
            patch.object(handler, "get_job_status", return_value={"status": "pending"}),
        ):
            handler.cancel_job(fleet_uuid, wait=True)

    fleets_api.cancel_fleet.assert_called_once()
    waiter.assert_called_once()


def test_cancel_job_raises_on_non_404_delete_error(mock_provider, project_id):
    """cancel_job surfaces non-404 errors from delete_fleet when delete=True."""
    with (
        patch(f"{_HANDLER_MOD}.ApiClient") as mock_api_client_cls,
        patch(f"{_HANDLER_MOD}.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        fleets_api.delete_fleet.side_effect = ApiException(status=409, reason="Conflict")
        mock_fleets_api_cls.return_value = fleets_api
        fleet_uuid = "f-00000000-0000-0000-0000-000000000005"

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        with (
            patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid),
            patch.object(handler, "_wait_until_terminal_or_canceled"),
            patch.object(handler, "get_job_status", return_value={"status": "running"}),
        ):
            with pytest.raises(ApiException) as exc:
                handler.cancel_job(fleet_uuid, wait=True, delete=True)

    assert exc.value.status == 409
    fleets_api.cancel_fleet.assert_called_once_with(project_id=project_id, id=fleet_uuid)
    fleets_api.delete_fleet.assert_called_once_with(project_id=project_id, id=fleet_uuid)


def test_cancel_job_allows_404_on_delete(mock_provider, project_id):
    """cancel_job tolerates 404 from delete_fleet as already deleted."""
    with (
        patch(f"{_HANDLER_MOD}.ApiClient") as mock_api_client_cls,
        patch(f"{_HANDLER_MOD}.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        fleets_api.delete_fleet.side_effect = ApiException(status=404, reason="Not Found")
        mock_fleets_api_cls.return_value = fleets_api
        fleet_uuid = "f-00000000-0000-0000-0000-000000000006"

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        with (
            patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid),
            patch.object(handler, "_wait_until_terminal_or_canceled"),
            patch.object(handler, "get_job_status", return_value={"status": "pending"}),
        ):
            handler.cancel_job(fleet_uuid, wait=True, delete=True)  # must not raise


def test_cancel_job_skips_cancel_when_already_terminal(mock_provider, project_id):
    """cancel_job does not call cancel_fleet when the fleet is already terminal."""
    with (
        patch(f"{_HANDLER_MOD}.ApiClient") as mock_api_client_cls,
        patch(f"{_HANDLER_MOD}.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        mock_fleets_api_cls.return_value = fleets_api
        fleet_uuid = "f-00000000-0000-0000-0000-000000000007"

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        with (
            patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid),
            patch.object(handler, "_wait_until_terminal_or_canceled") as waiter,
            patch.object(handler, "get_job_status", return_value={"status": "succeeded"}),
        ):
            handler.cancel_job(fleet_uuid, wait=True, delete=False)

    fleets_api.cancel_fleet.assert_not_called()
    waiter.assert_called_once()
    fleets_api.delete_fleet.assert_not_called()


def test_cancel_job_status_404_skips_cancel(mock_provider, project_id):
    """cancel_job skips cancel when get_job_status raises 404 (fleet already gone)."""
    with (
        patch(f"{_HANDLER_MOD}.ApiClient") as mock_api_client_cls,
        patch(f"{_HANDLER_MOD}.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        mock_fleets_api_cls.return_value = fleets_api
        fleet_uuid = "f-00000000-0000-0000-0000-000000000008"

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        with (
            patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid),
            patch.object(
                handler, "get_job_status", side_effect=ApiException(status=404, reason="Not Found")
            ),
            patch.object(handler, "_wait_until_terminal_or_canceled") as waiter,
        ):
            handler.cancel_job(fleet_uuid, wait=True, delete=False)

    fleets_api.cancel_fleet.assert_not_called()
    waiter.assert_called_once()


def test_cancel_job_times_out_raises_assertion(mock_provider, project_id):
    """cancel_job propagates AssertionError when the waiter times out."""
    with (
        patch(f"{_HANDLER_MOD}.ApiClient") as mock_api_client_cls,
        patch(f"{_HANDLER_MOD}.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        mock_fleets_api_cls.return_value = fleets_api
        fleet_uuid = "f-00000000-0000-0000-0000-000000000009"

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        with (
            patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid),
            patch.object(handler, "get_job_status", return_value={"status": "running"}),
            patch.object(
                handler, "_wait_until_terminal_or_canceled", side_effect=AssertionError("timeout")
            ),
        ):
            with pytest.raises(AssertionError):
                handler.cancel_job(fleet_uuid, wait=True, delete=False, timeout_seconds=0)

    fleets_api.cancel_fleet.assert_called_once_with(project_id=project_id, id=fleet_uuid)
    fleets_api.delete_fleet.assert_not_called()


def test_delete_job_happy_path(mock_provider, project_id):
    """delete_job resolves the ID and calls delete_fleet once."""
    with (
        patch(f"{_HANDLER_MOD}.ApiClient") as mock_api_client_cls,
        patch(f"{_HANDLER_MOD}.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        mock_fleets_api_cls.return_value = fleets_api
        fleet_uuid = "f-00000000-0000-0000-0000-000000000010"

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        with patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid):
            handler.delete_job(fleet_uuid)

    fleets_api.delete_fleet.assert_called_once_with(project_id=project_id, id=fleet_uuid)


def test_delete_job_ignores_404(mock_provider, project_id):
    """delete_job treats 404 as already deleted and does not raise."""
    with (
        patch(f"{_HANDLER_MOD}.ApiClient") as mock_api_client_cls,
        patch(f"{_HANDLER_MOD}.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        fleets_api.delete_fleet.side_effect = ApiException(status=404, reason="Not Found")
        mock_fleets_api_cls.return_value = fleets_api
        fleet_uuid = "f-00000000-0000-0000-0000-000000000011"

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        with patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid):
            handler.delete_job(fleet_uuid)  # must not raise

    fleets_api.delete_fleet.assert_called_once_with(project_id=project_id, id=fleet_uuid)


def test_delete_job_raises_on_non_404_error(mock_provider, project_id):
    """delete_job raises when delete_fleet fails with a non-404 error."""
    with (
        patch(f"{_HANDLER_MOD}.ApiClient") as mock_api_client_cls,
        patch(f"{_HANDLER_MOD}.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        fleets_api.delete_fleet.side_effect = ApiException(status=500, reason="Internal Error")
        mock_fleets_api_cls.return_value = fleets_api
        fleet_uuid = "f-00000000-0000-0000-0000-000000000012"

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        with patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid):
            with pytest.raises(ApiException) as exc:
                handler.delete_job(fleet_uuid)

    assert exc.value.status == 500


@patch(f"{_HANDLER_MOD}.FleetsApi")
@patch(f"{_HANDLER_MOD}.ApiClient")
def test_workers_get_worker_resource_allocation_happy_path(
    mock_api_client_cls, mock_fleets_api_cls, mock_provider, project_id
):
    """handler.workers.get_worker_resource_allocation returns correct dict and calculates duration."""
    handler, mock_fleets_api = _make_handler(
        mock_provider, project_id, mock_api_client_cls, mock_fleets_api_cls
    )

    mock_worker = MagicMock()
    mock_worker.status = "stopped"
    mock_worker.created_at = datetime(2026, 2, 9, 8, 45, 26)
    mock_worker.finished_at = datetime(2026, 2, 9, 8, 49, 23)
    mock_worker.status_details.profile = "cxf-2x4"
    mock_worker.status_details.zone = "eu-de-1"
    mock_worker.status_details.address = "10.243.0.10"
    mock_fleets_api.get_fleet_worker.return_value = mock_worker

    result = handler.workers.get_worker_resource_allocation(
        fleet_id="fleet-123", worker_name="fleet-123-worker-0"
    )

    mock_fleets_api.get_fleet_worker.assert_called_once_with(
        project_id=project_id, fleet_id="fleet-123", name="fleet-123-worker-0"
    )
    assert result["profile"] == "cxf-2x4"
    assert result["status"] == "stopped"
    assert result["zone"] == "eu-de-1"
    assert result["address"] == "10.243.0.10"
    assert result["duration_seconds"] == 237.0


@patch(f"{_HANDLER_MOD}.FleetsApi")
@patch(f"{_HANDLER_MOD}.ApiClient")
def test_workers_get_worker_resource_allocation_running_worker(
    mock_api_client_cls, mock_fleets_api_cls, mock_provider, project_id
):
    """handler.workers.get_worker_resource_allocation returns None duration for running workers."""
    handler, mock_fleets_api = _make_handler(
        mock_provider, project_id, mock_api_client_cls, mock_fleets_api_cls
    )

    mock_worker = MagicMock()
    mock_worker.status = "running"
    mock_worker.created_at = datetime(2026, 2, 9, 8, 45, 26)
    mock_worker.finished_at = None
    mock_worker.status_details.profile = "cxf-4x8"
    mock_fleets_api.get_fleet_worker.return_value = mock_worker

    result = handler.workers.get_worker_resource_allocation(
        fleet_id="fleet-456", worker_name="fleet-456-worker-1"
    )

    assert result["status"] == "running"
    assert result["finished_at"] is None
    assert result["duration_seconds"] is None


@patch(f"{_HANDLER_MOD}.FleetsApi")
@patch(f"{_HANDLER_MOD}.ApiClient")
def test_workers_get_worker_resource_allocation_no_status_details(
    mock_api_client_cls, mock_fleets_api_cls, mock_provider, project_id
):
    """handler.workers.get_worker_resource_allocation handles missing status_details gracefully."""
    handler, mock_fleets_api = _make_handler(
        mock_provider, project_id, mock_api_client_cls, mock_fleets_api_cls
    )

    mock_worker = MagicMock()
    mock_worker.status = "pending"
    mock_worker.created_at = datetime(2026, 2, 9, 8, 45, 26)
    mock_worker.finished_at = None
    mock_worker.status_details = None
    mock_fleets_api.get_fleet_worker.return_value = mock_worker

    result = handler.workers.get_worker_resource_allocation(
        fleet_id="fleet-789", worker_name="fleet-789-worker-0"
    )

    assert result["profile"] is None
    assert result["zone"] is None
    assert result["address"] is None
    assert result["duration_seconds"] is None


@patch(f"{_HANDLER_MOD}.FleetsApi")
@patch(f"{_HANDLER_MOD}.ApiClient")
def test_workers_get_worker_resource_allocation_raises_and_logs_api_exception(
    mock_api_client_cls, mock_fleets_api_cls, mock_provider, project_id, caplog
):
    """handler.workers.get_worker_resource_allocation logs an error and re-raises on ApiException."""
    handler, mock_fleets_api = _make_handler(
        mock_provider, project_id, mock_api_client_cls, mock_fleets_api_cls
    )
    mock_fleets_api.get_fleet_worker.side_effect = ApiException(status=404, reason="Not Found")

    with caplog.at_level(logging.ERROR, logger="FleetHandler"):
        with pytest.raises(ApiException):
            handler.workers.get_worker_resource_allocation(
                fleet_id="fleet-999", worker_name="nonexistent-worker"
            )

    assert "get_fleet_worker failed" in caplog.text
    assert str(project_id) in caplog.text
    assert "fleet-999" in caplog.text
    assert "nonexistent-worker" in caplog.text
    assert "404" in caplog.text
    assert "Not Found" in caplog.text


def test_build_run_volume_mounts_happy_path():
    """build_run_volume_mounts returns correct definitions including optional sub_path."""
    result = build_run_volume_mounts(
        mounts=[("/output", "my-pds", "user/job-1"), ("/logs", "log-pds", None)]
    )
    assert len(result) == 2
    assert result[0]["mount_path"] == "/output"
    assert result[0]["reference"] == "my-pds"
    assert result[0]["sub_path"] == "user/job-1"
    assert result[0]["type"] == "persistent_data_store"
    assert result[1]["mount_path"] == "/logs"
    assert "sub_path" not in result[1]


def test_build_run_volume_mounts_empty_raises():
    """build_run_volume_mounts raises ValueError on empty mounts list."""
    with pytest.raises(ValueError, match="mounts is required"):
        build_run_volume_mounts(mounts=[])


def test_build_run_env_variables_primary_only():
    """build_run_env_variables returns PRIMARY_LOG_DIR and PRIMARY_LOG_PATH."""
    result = build_run_env_variables(primary_mount_path="/output")
    names = {e["name"] for e in result}
    assert "PRIMARY_LOG_DIR" in names
    assert "PRIMARY_LOG_PATH" in names
    assert "SECONDARY_LOG_DIR" not in names


def test_build_run_env_variables_secondary_without_mount_raises():
    """build_run_env_variables raises when filter key given without secondary mount."""
    with pytest.raises(ValueError, match="secondary_mount_path is required"):
        build_run_env_variables(
            primary_mount_path="/output",
            secondary_log_filter_key="[public]",
        )


def test_build_run_commands_primary_only():
    """build_run_commands wraps command in a sh -c script with PRIMARY_LOG_PATH redirection."""
    result = build_run_commands(app_run_commands=["python", "main.py"])
    assert result[0] == "sh"
    assert result[1] == "-c"
    assert "python" in result[2]
    assert "PRIMARY_LOG_PATH" in result[2]


def test_build_run_commands_empty_raises():
    """build_run_commands raises ValueError when app_run_commands is empty."""
    with pytest.raises(ValueError, match="app_run_commands is required"):
        build_run_commands(app_run_commands=[])


def test_build_run_commands_with_secondary_log():
    """build_run_commands includes tee/awk piping when secondary_log_filter_key is set."""
    result = build_run_commands(
        app_run_commands=["python", "main.py"],
        secondary_log_filter_key="[public]",
    )
    assert "SECONDARY_LOG_PATH" in result[2]
    assert "awk" in result[2]
