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
Unit tests for the FleetHandler API
These tests validate job management behavior using mocked
parameters. No real infrastructure resources are provisioned.
"""

# pylint: disable=redefined-outer-name

from datetime import datetime
from unittest.mock import MagicMock, patch
import pytest
from swagger_client.rest import ApiException

from gateway.core.services.ibm_cloud.code_engine.fleets.fleet_handler import FleetHandler
from gateway.core.services.ibm_cloud.code_engine.fleets.fleet_utils import (
    build_run_volume_mounts,
    build_run_env_variables,
    build_run_commands,
)


@pytest.fixture
def mock_provider():
    """Provide a minimal IBMCloudClientProvider mock exposing config and auth fields."""
    provider = MagicMock()
    provider.config.code_engine_url = "https://codeengine.test.cloud.ibm.com/v1"
    provider.config.region = "us-south"
    provider.auth.token = "TEST_TOKEN"
    return provider


@pytest.fixture
def project_id():
    """Return a fake Code Engine project ID for tests."""
    return "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def base_payload():
    """Return a minimal, valid payload for submit_job tests."""
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


def _expected_body(base_payload, image_secret=None, extra_fields=None):
    """Build the expected body dict by merging optional fields."""
    body = dict(base_payload)
    if image_secret:
        body["image_secret"] = image_secret
    if extra_fields:
        body.update(extra_fields)
    return body


# ---------------------------------------------------------------------------
# submit_job tests
# ---------------------------------------------------------------------------


@patch("qf_fleets_client.api.job.job.FleetsApi")
@patch("qf_fleets_client.api.job.job.ApiClient")
def test_submit_job_happy_path(
    mock_api_client_cls, mock_fleets_api_cls, mock_provider, project_id, base_payload
):
    """Test should pass the correct body and project_id to FleetsApi.create_fleet and return its result."""

    mock_api_client = MagicMock()
    mock_api_client_cls.return_value = mock_api_client

    mock_fleets_api = MagicMock()
    mock_fleets_api_cls.return_value = mock_fleets_api

    created_resp = {"id": "fleet-id-123", "name": base_payload["name"]}
    mock_fleets_api.create_fleet.return_value = created_resp

    handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
    result = handler.submit_job(**base_payload)

    assert result == created_resp

    mock_api_client_cls.assert_called_once()
    mock_fleets_api_cls.assert_called_once_with(mock_api_client)

    mock_fleets_api.create_fleet.assert_called_once()
    call_kwargs = mock_fleets_api.create_fleet.call_args.kwargs
    assert call_kwargs["project_id"] == project_id
    assert call_kwargs["body"] == _expected_body(base_payload)


@patch("qf_fleets_client.api.job.job.FleetsApi")
@patch("qf_fleets_client.api.job.job.ApiClient")
def test_submit_job_with_optional_fields(
    mock_api_client_cls, mock_fleets_api_cls, mock_provider, project_id, base_payload
):
    """Test should add image_secret and merge extra_fields into the request body."""

    mock_api_client = MagicMock()
    mock_api_client_cls.return_value = mock_api_client

    mock_fleets_api = MagicMock()
    mock_fleets_api_cls.return_value = mock_fleets_api

    extra = {
        "command": ["/bin/sh", "-lc", "echo hello"],
        "args": ["--foo", "bar"],
        "scale_max_execution_time": 600,
    }
    image_secret = "cr-secret-1"

    handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
    handler.submit_job(**base_payload, image_secret=image_secret, extra_fields=extra)

    mock_fleets_api.create_fleet.assert_called_once()
    call_kwargs = mock_fleets_api.create_fleet.call_args.kwargs
    assert call_kwargs["project_id"] == project_id
    assert call_kwargs["body"] == _expected_body(
        base_payload, image_secret=image_secret, extra_fields=extra
    )


@patch("qf_fleets_client.api.job.job.FleetsApi")
@patch("qf_fleets_client.api.job.job.ApiClient")
def test_submit_job_raises_and_logs_api_exception(
    # pylint: disable=too-many-positional-arguments
    mock_api_client_cls,
    mock_fleets_api_cls,
    mock_provider,
    project_id,
    base_payload,
    capsys,
):
    """Test should print a helpful line and re-raise when ApiException occurs."""
    mock_api_client = MagicMock()
    mock_api_client_cls.return_value = mock_api_client

    exc = ApiException(status=403, reason="Forbidden")
    mock_fleets_api = MagicMock()
    mock_fleets_api.create_fleet.side_effect = exc
    mock_fleets_api_cls.return_value = mock_fleets_api

    handler = FleetHandler(client_provider=mock_provider, project_id=project_id)

    with pytest.raises(ApiException):
        handler.submit_job(**base_payload)

    out, _ = capsys.readouterr()
    assert "create_fleet failed" in out
    assert str(project_id) in out
    assert "403" in out or "status=403" in out
    assert "Forbidden" in out


@patch("qf_fleets_client.api.job.job.FleetsApi")
@patch("qf_fleets_client.api.job.job.ApiClient")
def test_FleetHandler_initializes_api_clients_with_provider_config(
    mock_api_client_cls, mock_fleets_api_cls, mock_provider, project_id, base_payload
):
    """Test should set host and Authorization bearer token from the provider."""
    seen_cfg = {}

    def _api_client_side_effect(cfg):
        seen_cfg["host"] = getattr(cfg, "host", None)
        seen_cfg["api_key"] = dict(getattr(cfg, "api_key", {}))
        seen_cfg["api_key_prefix"] = dict(getattr(cfg, "api_key_prefix", {}))
        return MagicMock()

    mock_api_client_cls.side_effect = _api_client_side_effect
    mock_fleets_api_cls.return_value = MagicMock()

    handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
    handler.submit_job(**base_payload)

    assert seen_cfg["host"] == mock_provider.config.code_engine_url
    assert seen_cfg["api_key"].get("Authorization") == mock_provider.auth.token
    assert seen_cfg["api_key_prefix"].get("Authorization") == "Bearer"


@patch("qf_fleets_client.api.job.job.FleetsApi")
@patch("qf_fleets_client.api.job.job.ApiClient")
def test_submit_job_with_builder_extra_fields(
    mock_api_client_cls, mock_fleets_api_cls, mock_provider, project_id, base_payload
):
    """Test submit_job with extra_fields built from utils builder functions."""
    mock_api_client = MagicMock()
    mock_api_client_cls.return_value = mock_api_client

    mock_fleets_api = MagicMock()
    mock_fleets_api_cls.return_value = mock_fleets_api

    created_resp = {"id": "fleet-id-123", "name": base_payload["name"]}
    mock_fleets_api.create_fleet.return_value = created_resp

    # Build extra_fields using the utils functions
    run_volume_mounts = build_run_volume_mounts(
        mounts=[("/output", "test-pds", "test_user/fleet-1")]
    )
    run_env_variables = build_run_env_variables(primary_mount_path="/output")
    run_commands = build_run_commands(app_run_commands=["python", "main.py"])

    extra_fields = {
        "run_volume_mounts": run_volume_mounts,
        "run_env_variables": run_env_variables,
        "run_commands": run_commands,
    }

    handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
    result = handler.submit_job(**base_payload, extra_fields=extra_fields)

    assert result == created_resp

    mock_fleets_api.create_fleet.assert_called_once()
    call_kwargs = mock_fleets_api.create_fleet.call_args.kwargs
    body = call_kwargs["body"]

    # Check that run_volume_mounts was added
    assert "run_volume_mounts" in body
    assert len(body["run_volume_mounts"]) == 1
    mount = body["run_volume_mounts"][0]
    assert mount["mount_path"] == "/output"
    assert mount["reference"] == "test-pds"
    assert mount["type"] == "persistent_data_store"
    assert mount["sub_path"] == "test_user/fleet-1"

    # Check that run_commands was added with log redirection
    assert "run_commands" in body
    assert len(body["run_commands"]) == 3
    assert body["run_commands"][0] == "sh"
    assert body["run_commands"][1] == "-c"
    assert "mkdir -p" in body["run_commands"][2]


# ---------------------------------------------------------------------------
# Builder utils tests (pure functions)
# ---------------------------------------------------------------------------


def test_build_run_volume_mounts_happy_path():
    """Test build_run_volume_mounts returns correct volume mount definitions."""
    result = build_run_volume_mounts(
        mounts=[("/output", "my-pds", "user/job-1"), ("/logs", "log-pds", None)]
    )
    assert len(result) == 2
    assert result[0]["mount_path"] == "/output"
    assert result[0]["reference"] == "my-pds"
    assert result[0]["sub_path"] == "user/job-1"
    assert result[1]["mount_path"] == "/logs"
    assert result[1]["reference"] == "log-pds"
    assert "sub_path" not in result[1]


def test_build_run_volume_mounts_empty_raises():
    """Test build_run_volume_mounts raises on empty mounts."""
    with pytest.raises(ValueError, match="mounts is required"):
        build_run_volume_mounts(mounts=[])


def test_build_run_env_variables_secondary_without_mount_raises():
    """Test build_run_env_variables raises when filter key given without secondary mount."""
    with pytest.raises(ValueError, match="secondary_mount_path is required"):
        build_run_env_variables(
            primary_mount_path="/output",
            secondary_log_filter_key="[public]",
        )


# ---------------------------------------------------------------------------
# Worker sub-manager tests (handler.workers.xxx)
# ---------------------------------------------------------------------------


@patch("qf_fleets_client.api.job.job.FleetsApi")
@patch("qf_fleets_client.api.job.job.ApiClient")
def test_get_worker_resource_consumption_happy_path(
    mock_api_client_cls, mock_fleets_api_cls, mock_provider, project_id
):
    """Test should retrieve worker details and calculate duration correctly."""
    mock_api_client = MagicMock()
    mock_api_client_cls.return_value = mock_api_client

    mock_fleets_api = MagicMock()
    mock_fleets_api_cls.return_value = mock_fleets_api

    # Create mock worker with status details
    mock_worker = MagicMock()
    mock_worker.status = "stopped"
    mock_worker.created_at = datetime(2026, 2, 9, 8, 45, 26)
    mock_worker.finished_at = datetime(2026, 2, 9, 8, 49, 23)

    mock_status_details = MagicMock()
    mock_status_details.profile = "cxf-2x4"
    mock_status_details.zone = "eu-de-1"
    mock_status_details.address = "10.243.0.10"
    mock_worker.status_details = mock_status_details

    mock_fleets_api.get_fleet_worker.return_value = mock_worker

    handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
    result = handler.get_worker_resource_consumption(
        fleet_id="fleet-123", worker_name="fleet-123-worker-0"
    )

    # Verify API was called correctly
    mock_fleets_api.get_fleet_worker.assert_called_once_with(
        project_id=project_id, fleet_id="fleet-123", name="fleet-123-worker-0"
    )

    # Verify result structure
    assert result["worker"] == mock_worker
    assert result["profile"] == "cxf-2x4"
    assert result["status"] == "stopped"
    assert result["zone"] == "eu-de-1"
    assert result["address"] == "10.243.0.10"
    assert result["created_at"] == datetime(2026, 2, 9, 8, 45, 26)
    assert result["finished_at"] == datetime(2026, 2, 9, 8, 49, 23)

    # Verify duration calculation (237 seconds)
    expected_duration = (
        datetime(2026, 2, 9, 8, 49, 23) - datetime(2026, 2, 9, 8, 45, 26)
    ).total_seconds()
    assert result["duration_seconds"] == expected_duration
    assert result["duration_seconds"] == 237.0


def test_get_job_status_uuid_happy_path(mock_provider, project_id):
    """
    Verify that get_job_status returns the expected summary of the specified fleet ID.
    Uses context-managed patches so pytest does not treat mock arguments as fixtures.
    """
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
        patch("qf_fleets_client.api.job.job.ApiClient") as mock_api_client_cls,
        patch("qf_fleets_client.api.job.job.FleetsApi") as mock_fleets_api_cls,
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


@patch("qf_fleets_client.api.job.job.FleetsApi")
@patch("qf_fleets_client.api.job.job.ApiClient")
def test_get_worker_resource_consumption_running_worker(
    mock_api_client_cls, mock_fleets_api_cls, mock_provider, project_id
):
    """Test should handle running worker without finished_at timestamp."""
    mock_api_client = MagicMock()
    mock_api_client_cls.return_value = mock_api_client

    mock_fleets_api = MagicMock()
    mock_fleets_api_cls.return_value = mock_fleets_api

    # Create mock worker that's still running
    mock_worker = MagicMock()
    mock_worker.status = "running"
    mock_worker.created_at = datetime(2026, 2, 9, 8, 45, 26)
    mock_worker.finished_at = None

    mock_status_details = MagicMock()
    mock_status_details.profile = "cxf-4x8"
    mock_status_details.zone = "eu-de-2"
    mock_status_details.address = "10.243.0.20"
    mock_worker.status_details = mock_status_details

    mock_fleets_api.get_fleet_worker.return_value = mock_worker

    handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
    result = handler.get_worker_resource_consumption(
        fleet_id="fleet-456", worker_name="fleet-456-worker-1"
    )

    # Verify result structure
    assert result["worker"] == mock_worker
    assert result["profile"] == "cxf-4x8"
    assert result["status"] == "running"
    assert result["created_at"] == datetime(2026, 2, 9, 8, 45, 26)
    assert result["finished_at"] is None
    assert result["duration_seconds"] is None  # No duration for running worker


def test_get_job_status_name_happy_path(mock_provider, project_id):
    """
    Verify that get_job_status returns the expected summary of the specified fleet name,
    using fallback fields when 'status' is absent (uses 'state', 'created', 'updated').
    """
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
        patch("qf_fleets_client.api.job.job.ApiClient") as mock_api_client_cls,
        patch("qf_fleets_client.api.job.job.FleetsApi") as mock_fleets_api_cls,
    ):

        mock_api_client_cls.return_value = MagicMock()

        fleets_api = MagicMock()
        fleets_api.get_fleet.return_value = payload  # plain dict
        mock_fleets_api_cls.return_value = fleets_api

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        with patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid):
            result = handler.get_job_status(fleet_name)

        assert result["id"] == fleet_uuid
        assert result["name"] == fleet_name
        assert result["status"] == "succeeded"
        assert result["desired_instances"] == 1
        assert result["running_instances"] == 0
        assert result["created_at"] == "2026-02-18T10:00:00Z"
        assert result["updated_at"] == "2026-02-18T10:05:00Z"
        assert result["raw"] == payload
        fleets_api.get_fleet.assert_called_once_with(project_id=project_id, id=fleet_uuid)


@patch("qf_fleets_client.api.job.job.FleetsApi")
@patch("qf_fleets_client.api.job.job.ApiClient")
def test_get_worker_resource_consumption_no_status_details(
    mock_api_client_cls, mock_fleets_api_cls, mock_provider, project_id
):
    """Test should handle worker without status_details gracefully."""
    mock_api_client = MagicMock()
    mock_api_client_cls.return_value = mock_api_client

    mock_fleets_api = MagicMock()
    mock_fleets_api_cls.return_value = mock_fleets_api

    # Create mock worker without status details
    mock_worker = MagicMock()
    mock_worker.status = "pending"
    mock_worker.created_at = datetime(2026, 2, 9, 8, 45, 26)
    mock_worker.finished_at = None
    mock_worker.status_details = None

    mock_fleets_api.get_fleet_worker.return_value = mock_worker

    handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
    result = handler.get_worker_resource_consumption(
        fleet_id="fleet-789", worker_name="fleet-789-worker-0"
    )

    # Verify result structure with None values for status_details fields
    assert result["worker"] == mock_worker
    assert result["profile"] is None
    assert result["zone"] is None
    assert result["address"] is None
    assert result["status"] == "pending"
    assert result["duration_seconds"] is None


def test_get_job_status_name_not_found_raises_value_error(mock_provider, project_id):
    """
    Verify that get_job_status propagates ValueError when a non-UUID identifier
    is provided and resolving the fleet by name fails.
    """
    with (
        patch("qf_fleets_client.api.job.job.ApiClient") as mock_api_client_cls,
        patch("qf_fleets_client.api.job.job.FleetsApi") as mock_fleets_api_cls,
    ):

        mock_api_client_cls.return_value = MagicMock()
        mock_fleets_api_cls.return_value = MagicMock()

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)

        with patch.object(handler, "_resolve_fleet_id", side_effect=ValueError("Fleet not found")):
            with pytest.raises(ValueError) as exc:
                handler.get_job_status("does-not-exist")
        assert "not" in str(exc.value).lower() and "found" in str(exc.value).lower()


def test_get_job_status_api_exception(mock_provider, project_id):
    """
    Verify that get_job_status propagates ApiException raised by FleetsApi.get_fleet.
    """
    with (
        patch("qf_fleets_client.api.job.job.ApiClient") as mock_api_client_cls,
        patch("qf_fleets_client.api.job.job.FleetsApi") as mock_fleets_api_cls,
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
        fleets_api.get_fleet.assert_called_once()


# ---------------------------------------------------------------------------
# COS sub-manager tests (handler.cos.xxx)
# ---------------------------------------------------------------------------


@patch("qf_fleets_client.api.job.cos.COS")
@patch("qf_fleets_client.api.job.job.FleetsApi")
@patch("qf_fleets_client.api.job.job.ApiClient")
def test_cos_logs_retrieves_from_cos(
    mock_api_client_cls, mock_fleets_api_cls, mock_cos_cls, mock_provider, project_id
):
    """Test handler.cos.logs() should retrieve log file from COS with correct path."""
    mock_api_client = MagicMock()
    mock_api_client_cls.return_value = mock_api_client

    mock_fleets_api = MagicMock()
    mock_fleets_api_cls.return_value = mock_fleets_api

    # Mock COS
    mock_cos = MagicMock()
    mock_cos_cls.return_value = mock_cos

    # Mock bucket operations
    log_content = b"Test log content"
    mock_cos.bucket.get_object_bytes.return_value = log_content
    mock_cos.bucket.wait_until_object_exists.return_value = None

    cos_config = {
        "resource_group_id": "test-rg",
        "cos_name": "test-cos",
        "cos_key_name": "test-key",
        "bucket_region": "us-south",
    }

    handler = FleetHandler(
        client_provider=mock_provider, project_id=project_id, cos_config=cos_config
    )

    result = handler.cos.logs(
        bucket_name="test-bucket",
        log_key="test_user/test-fleet/test.log",
        save_locally=False,
        wait_for_availability=False,
    )

    assert result == log_content.decode("utf-8")

    # Verify COS was initialized correctly
    mock_cos_cls.assert_called_once()
    call_kwargs = mock_cos_cls.call_args.kwargs
    assert call_kwargs["resource_group_id"] == "test-rg"
    assert call_kwargs["cos_name"] == "test-cos"
    assert call_kwargs["cos_key_name"] == "test-key"

    # Verify get_object_bytes was called with correct bucket and key
    mock_cos.bucket.get_object_bytes.assert_called_once_with(
        bucket="test-bucket",
        key="test_user/test-fleet/test.log",
    )


@patch("qf_fleets_client.api.job.job.FleetsApi")
@patch("qf_fleets_client.api.job.job.ApiClient")
def test_cos_logs_without_cos_config_raises_error(
    mock_api_client_cls, mock_fleets_api_cls, mock_provider, project_id
):
    """Test handler.cos.logs() should raise ValueError when no cos_config provided."""
    mock_api_client = MagicMock()
    mock_api_client_cls.return_value = mock_api_client

    mock_fleets_api = MagicMock()


@patch("qf_fleets_client.api.job.job.FleetsApi")
@patch("qf_fleets_client.api.job.job.ApiClient")
def test_get_worker_resource_consumption_raises_and_logs_api_exception(
    mock_api_client_cls, mock_fleets_api_cls, mock_provider, project_id, capsys
):
    """Test should print a helpful line and re-raise when ApiException occurs."""
    mock_api_client = MagicMock()
    mock_api_client_cls.return_value = mock_api_client

    exc = ApiException(status=404, reason="Not Found")
    mock_fleets_api = MagicMock()
    mock_fleets_api.get_fleet_worker.side_effect = exc
    mock_fleets_api_cls.return_value = mock_fleets_api

    # No cos_config
    handler = FleetHandler(client_provider=mock_provider, project_id=project_id)

    with pytest.raises(ValueError, match="COS not configured"):
        handler.cos.logs(
            bucket_name="test-bucket",
            log_key="some/key.log",
        )


@patch("qf_fleets_client.api.job.cos.COS")
@patch("qf_fleets_client.api.job.job.FleetsApi")
@patch("qf_fleets_client.api.job.job.ApiClient")
def test_cos_logs_waits_for_availability(
    mock_api_client_cls, mock_fleets_api_cls, mock_cos_cls, mock_provider, project_id
):
    """Test handler.cos.logs() should call wait_until_object_exists when wait_for_availability=True."""
    mock_api_client = MagicMock()
    mock_api_client_cls.return_value = mock_api_client

    mock_fleets_api = MagicMock()
    mock_fleets_api_cls.return_value = mock_fleets_api

    # Mock COS
    mock_cos = MagicMock()
    mock_cos_cls.return_value = mock_cos

    # Mock bucket operations
    log_content = b"Test log content"
    mock_cos.bucket.get_object_bytes.return_value = log_content
    mock_cos.bucket.wait_until_object_exists.return_value = None

    cos_config = {
        "resource_group_id": "test-rg",
        "cos_name": "test-cos",
        "cos_key_name": "test-key",
    }

    handler = FleetHandler(
        client_provider=mock_provider, project_id=project_id, cos_config=cos_config
    )

    result = handler.cos.logs(
        bucket_name="test-bucket",
        log_key="user/job/logs.log",
        save_locally=False,
        wait_for_availability=True,
        timeout=60,
        poll_interval=1,
    )

    assert result == log_content.decode("utf-8")

    # Verify wait_until_object_exists was called
    mock_cos.bucket.wait_until_object_exists.assert_called_once_with(
        bucket="test-bucket",
        key="user/job/logs.log",
        timeout_seconds=60,
        poll_interval=1,
    )


@patch("qf_fleets_client.api.job.cos.COS")
@patch("qf_fleets_client.api.job.job.FleetsApi")
@patch("qf_fleets_client.api.job.job.ApiClient")
def test_cos_wait_for_object(
    mock_api_client_cls, mock_fleets_api_cls, mock_cos_cls, mock_provider, project_id
):
    """Test handler.cos.wait_for_object() delegates to COS bucket waiter."""
    mock_api_client_cls.return_value = MagicMock()
    mock_fleets_api_cls.return_value = MagicMock()

    mock_cos = MagicMock()
    mock_cos_cls.return_value = mock_cos

    cos_config = {
        "resource_group_id": "test-rg",
        "cos_name": "test-cos",
        "cos_key_name": "test-key",
    }

    handler = FleetHandler(
        client_provider=mock_provider, project_id=project_id, cos_config=cos_config
    )

    handler.cos.wait_for_object(bucket_name="my-bucket", key="path/to/obj", timeout=30)

    mock_cos.bucket.wait_until_object_exists.assert_called_once_with(
        bucket="my-bucket",
        key="path/to/obj",
        timeout_seconds=30,
        poll_interval=2,
    )


@patch("qf_fleets_client.api.job.cos.COS")
@patch("qf_fleets_client.api.job.job.FleetsApi")
@patch("qf_fleets_client.api.job.job.ApiClient")
def test_cos_delete_object(
    mock_api_client_cls, mock_fleets_api_cls, mock_cos_cls, mock_provider, project_id
):
    """Test handler.cos.delete_object() delegates to COS bucket delete."""
    mock_api_client_cls.return_value = MagicMock()
    mock_fleets_api_cls.return_value = MagicMock()

    mock_cos = MagicMock()
    mock_cos_cls.return_value = mock_cos

    cos_config = {
        "resource_group_id": "test-rg",
        "cos_name": "test-cos",
        "cos_key_name": "test-key",
    }

    handler = FleetHandler(
        client_provider=mock_provider, project_id=project_id, cos_config=cos_config
    )

    handler.cos.delete_object(bucket_name="my-bucket", key="path/to/obj", wait=True, timeout=60)

    mock_cos.bucket.delete_object.assert_called_once_with(
        bucket="my-bucket",
        key="path/to/obj",
        wait=True,
        timeout_seconds=60,
        poll_interval=2,
    )

    # ---------------------------------------------------------------------------
    # cancel_job tests
    # ---------------------------------------------------------------------------
    with pytest.raises(ApiException):
        handler.get_worker_resource_consumption(
            fleet_id="fleet-999", worker_name="nonexistent-worker"
        )

    out, _ = capsys.readouterr()
    assert "get_fleet_worker failed" in out
    assert str(project_id) in out
    assert "fleet-999" in out
    assert "nonexistent-worker" in out
    assert "404" in out or "status=404" in out
    assert "Not Found" in out


def test_get_job_status_api_exception(mock_provider, project_id):
    """
    Verify that get_job_status propagates ApiException raised by FleetsApi.get_fleet.
    """
    with (
        patch("qf_fleets_client.api.job.job.ApiClient") as mock_api_client_cls,
        patch("qf_fleets_client.api.job.job.FleetsApi") as mock_fleets_api_cls,
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
        fleets_api.get_fleet.assert_called_once()


def test_cancel_job_happy_path_waits_no_delete_by_default(mock_provider, project_id):
    """cancel_job:
    - resolves identifier to UUID
    - if status pending/running -> calls cancel_fleet(...)
    - waits via _wait_until_terminal_or_canceled(...)
    - DOES NOT delete by default (delete=False)
    """
    with (
        patch("qf_fleets_client.api.job.job.ApiClient") as mock_api_client_cls,
        patch("qf_fleets_client.api.job.job.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        mock_fleets_api_cls.return_value = fleets_api

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        fleet_uuid = "f-00000000-0000-0000-0000-000000000001"

        with (
            patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid),
            patch.object(handler, "_wait_until_terminal_or_canceled") as waiter,
            patch.object(handler, "get_job_status", return_value={"status": "running"}),
        ):
            handler.cancel_job(
                fleet_uuid, wait=True, timeout_seconds=10, poll_interval_seconds=0.01
            )

        fleets_api.cancel_fleet.assert_called_once_with(project_id=project_id, id=fleet_uuid)
        waiter.assert_called_once()
        fleets_api.delete_fleet.assert_not_called()


def test_cancel_job_waits_and_deletes_when_flag_set(mock_provider, project_id):
    """cancel_job with delete=True will delete after waiting."""
    with (
        patch("qf_fleets_client.api.job.job.ApiClient") as mock_api_client_cls,
        patch("qf_fleets_client.api.job.job.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        mock_fleets_api_cls.return_value = fleets_api

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        fleet_uuid = "f-00000000-0000-0000-0000-000000000002"

        with (
            patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid),
            patch.object(handler, "_wait_until_terminal_or_canceled") as waiter,
            patch.object(handler, "get_job_status", return_value={"status": "pending"}),
        ):
            handler.cancel_job(fleet_uuid, wait=True, delete=True)

        fleets_api.cancel_fleet.assert_called_once_with(project_id=project_id, id=fleet_uuid)
        waiter.assert_called_once()
        fleets_api.delete_fleet.assert_called_once_with(project_id=project_id, id=fleet_uuid)


def test_cancel_job_no_wait_skips_poller_and_no_delete_by_default(mock_provider, project_id):
    """cancel_job with wait=False calls cancel and DOES NOT call the poller; no delete by default."""
    with (
        patch("qf_fleets_client.api.job.job.ApiClient") as mock_api_client_cls,
        patch("qf_fleets_client.api.job.job.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        mock_fleets_api_cls.return_value = fleets_api

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        fleet_uuid = "f-00000000-0000-0000-0000-000000000003"

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
    """cancel_job should ignore ApiException(404) from cancel_fleet and continue flow (no delete by default)."""
    with (
        patch("qf_fleets_client.api.job.job.ApiClient") as mock_api_client_cls,
        patch("qf_fleets_client.api.job.job.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        fleets_api.cancel_fleet.side_effect = ApiException(status=404, reason="Not Found")
        mock_fleets_api_cls.return_value = fleets_api

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        fleet_uuid = "f-00000000-0000-0000-0000-000000000004"

        with (
            patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid),
            patch.object(handler, "_wait_until_terminal_or_canceled") as waiter,
            patch.object(handler, "get_job_status", return_value={"status": "pending"}),
        ):
            handler.cancel_job(fleet_uuid, wait=True)

        fleets_api.cancel_fleet.assert_called_once()
        waiter.assert_called_once()
        fleets_api.delete_fleet.assert_not_called()


def test_cancel_job_raises_on_non_404_delete_error_when_delete_true(mock_provider, project_id):
    """cancel_job must surface non-404 errors from delete_fleet when delete=True."""
    with (
        patch("qf_fleets_client.api.job.job.ApiClient") as mock_api_client_cls,
        patch("qf_fleets_client.api.job.job.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        fleets_api.delete_fleet.side_effect = ApiException(status=409, reason="Conflict")
        mock_fleets_api_cls.return_value = fleets_api

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        fleet_uuid = "f-00000000-0000-0000-0000-000000000005"

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


def test_cancel_job_allows_404_on_delete_when_delete_true(mock_provider, project_id):
    """cancel_job should tolerate delete_fleet ApiException(404) as 'already gone' when delete=True."""
    with (
        patch("qf_fleets_client.api.job.job.ApiClient") as mock_api_client_cls,
        patch("qf_fleets_client.api.job.job.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        fleets_api.delete_fleet.side_effect = ApiException(status=404, reason="Not Found")
        mock_fleets_api_cls.return_value = fleets_api

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        fleet_uuid = "f-00000000-0000-0000-0000-000000000006"

        with (
            patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid),
            patch.object(handler, "_wait_until_terminal_or_canceled"),
            patch.object(handler, "get_job_status", return_value={"status": "pending"}),
        ):
            handler.cancel_job(fleet_uuid, wait=True, delete=True)  # should not raise

        fleets_api.cancel_fleet.assert_called_once_with(project_id=project_id, id=fleet_uuid)
        fleets_api.delete_fleet.assert_called_once_with(project_id=project_id, id=fleet_uuid)


def test_cancel_job_skips_cancel_when_already_terminal(mock_provider, project_id):
    """If status is terminal, do not call cancel; delete only if requested."""
    with (
        patch("qf_fleets_client.api.job.job.ApiClient") as mock_api_client_cls,
        patch("qf_fleets_client.api.job.job.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        mock_fleets_api_cls.return_value = fleets_api

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        fleet_uuid = "f-00000000-0000-0000-0000-000000000007"

        with (
            patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid),
            patch.object(handler, "_wait_until_terminal_or_canceled") as waiter,
            patch.object(handler, "get_job_status", return_value={"status": "succeeded"}),
        ):
            handler.cancel_job(fleet_uuid, wait=True, delete=False)

        fleets_api.cancel_fleet.assert_not_called()
        waiter.assert_called_once()
        fleets_api.delete_fleet.assert_not_called()


def test_cancel_job_status_404_skips_cancel_and_wait_returns(mock_provider, project_id):
    """If get_job_status raises 404, skip cancel; waiting should treat disappearance as terminal."""
    with (
        patch("qf_fleets_client.api.job.job.ApiClient") as mock_api_client_cls,
        patch("qf_fleets_client.api.job.job.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        mock_fleets_api_cls.return_value = fleets_api

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        fleet_uuid = "f-00000000-0000-0000-0000-000000000008"

        def status_404(_fid):
            raise ApiException(status=404, reason="Not Found")

        with (
            patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid),
            patch.object(handler, "get_job_status", side_effect=status_404),
        ):
            with patch.object(handler, "_wait_until_terminal_or_canceled") as waiter:
                handler.cancel_job(fleet_uuid, wait=True, delete=False)

        fleets_api.cancel_fleet.assert_not_called()
        waiter.assert_called_once()
        fleets_api.delete_fleet.assert_not_called()


def test_cancel_job_times_out_raises_assertion(mock_provider, project_id):
    """If waiting never reaches terminal, cancel may have been attempted, but timeout raises AssertionError."""
    with (
        patch("qf_fleets_client.api.job.job.ApiClient") as mock_api_client_cls,
        patch("qf_fleets_client.api.job.job.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        mock_fleets_api_cls.return_value = fleets_api

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        fleet_uuid = "f-00000000-0000-0000-0000-000000000009"

        with (
            patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid),
            patch.object(handler, "get_job_status", return_value={"status": "running"}),
            patch.object(
                handler, "_wait_until_terminal_or_canceled", side_effect=AssertionError("timeout")
            ),
        ):
            with pytest.raises(AssertionError):
                handler.cancel_job(
                    fleet_uuid,
                    wait=True,
                    delete=False,
                    timeout_seconds=0,
                    poll_interval_seconds=0.01,
                )

        fleets_api.cancel_fleet.assert_called_once_with(project_id=project_id, id=fleet_uuid)
        # No delete by default
        fleets_api.delete_fleet.assert_not_called()


# ---------------------------------------------------------------------------
# delete_job tests
# ---------------------------------------------------------------------------


def test_delete_job_happy_path(mock_provider, project_id):
    """delete_job should resolve the ID and call delete_fleet once."""
    with (
        patch("qf_fleets_client.api.job.job.ApiClient") as mock_api_client_cls,
        patch("qf_fleets_client.api.job.job.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        mock_fleets_api_cls.return_value = fleets_api

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        fleet_uuid = "f-00000000-0000-0000-0000-000000000010"

        with patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid):
            handler.delete_job(fleet_uuid)

        fleets_api.delete_fleet.assert_called_once_with(project_id=project_id, id=fleet_uuid)


def test_delete_job_ignores_404(mock_provider, project_id):
    """delete_job should treat 404 as already deleted and not raise."""
    with (
        patch("qf_fleets_client.api.job.job.ApiClient") as mock_api_client_cls,
        patch("qf_fleets_client.api.job.job.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        fleets_api.delete_fleet.side_effect = ApiException(status=404, reason="Not Found")
        mock_fleets_api_cls.return_value = fleets_api

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        fleet_uuid = "f-00000000-0000-0000-0000-000000000011"

        with patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid):
            handler.delete_job(fleet_uuid)  # should not raise

        fleets_api.delete_fleet.assert_called_once_with(project_id=project_id, id=fleet_uuid)


def test_delete_job_raises_on_non_404_error(mock_provider, project_id):
    """delete_job should raise when delete_fleet fails with non-404 errors."""
    with (
        patch("qf_fleets_client.api.job.job.ApiClient") as mock_api_client_cls,
        patch("qf_fleets_client.api.job.job.FleetsApi") as mock_fleets_api_cls,
    ):
        mock_api_client_cls.return_value = MagicMock()
        fleets_api = MagicMock()
        fleets_api.delete_fleet.side_effect = ApiException(status=500, reason="Internal Error")
        mock_fleets_api_cls.return_value = fleets_api

        handler = FleetHandler(client_provider=mock_provider, project_id=project_id)
        fleet_uuid = "f-00000000-0000-0000-0000-000000000012"

        with patch.object(handler, "_resolve_fleet_id", return_value=fleet_uuid):
            with pytest.raises(ApiException) as exc:
                handler.delete_job(fleet_uuid)
        assert exc.value.status == 500

        fleets_api.delete_fleet.assert_called_once_with(project_id=project_id, id=fleet_uuid)
