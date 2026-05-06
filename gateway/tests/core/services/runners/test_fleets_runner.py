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

"""Unit tests for FleetsRunner."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from core.ibm_cloud.code_engine.ce_client.rest import ApiException
from core.services.runners.runner import RunnerError
from core.services.runners.fleets_runner import FleetsRunner

_RUNNER_MOD = "core.services.runners.fleets_runner"


@pytest.fixture(autouse=True)
def _clear_is_active_cache():
    FleetsRunner._is_active_cache._store.clear()


def _make_runner(fleet_id: str | None = None) -> tuple[FleetsRunner, MagicMock]:
    """Build a FleetsRunner wired to mock Job and FleetHandler.

    Args:
        fleet_id: Optional fleet ID to pre-set on the job.

    Returns:
        Tuple of ``(runner, mock_handler)``.
    """
    mock_job = MagicMock()
    mock_job.fleet_id = fleet_id
    mock_job.SUCCEEDED = "SUCCEEDED"
    mock_job.FAILED = "FAILED"
    mock_job.STOPPED = "STOPPED"
    mock_job.PENDING = "PENDING"
    mock_job.RUNNING = "RUNNING"

    runner = FleetsRunner(mock_job)
    mock_handler = MagicMock()
    runner._handler = mock_handler  # pylint: disable=protected-access
    runner._project = MagicMock()  # pylint: disable=protected-access
    runner._connected = True  # pylint: disable=protected-access
    return runner, mock_handler


@contextmanager
def _patch_settings(**overrides):
    """Mock Django settings with sensible defaults for FleetsRunner tests."""
    defaults = {
        "CE_HMAC_SECRET_NAME": None,
        "IBM_CLOUD_API_KEY": "test-api-key",
        "CE_ICR_PULL_SECRET": "test-pull-secret",
        "FLEETS_DEFAULT_IMAGE": "default-image:latest",
        "FLEETS_DEFAULT_CPU_LIMIT": "1",
        "FLEETS_DEFAULT_MEMORY_LIMIT": "2G",
        "FLEETS_DEFAULT_MAX_INSTANCES": 1,
        "DEFAULT_COMPUTE_PROFILE": "cx3d-4x16",
    }
    defaults.update(overrides)
    with patch(f"{_RUNNER_MOD}.settings") as mock_settings:
        for key, value in defaults.items():
            setattr(mock_settings, key, value)
        yield mock_settings


def _make_submit_runner() -> tuple[FleetsRunner, MagicMock]:
    """Build a FleetsRunner pre-wired for submit() without COS.

    Returns:
        Tuple of ``(runner, mock_handler)`` where handler.submit_job
        returns a fleet with id="fleet-abc".
    """
    mock_job = MagicMock()
    mock_job.fleet_id = None
    mock_job.id = "job-uuid"
    mock_job.SUCCEEDED = "SUCCEEDED"
    mock_job.FAILED = "FAILED"
    mock_job.STOPPED = "STOPPED"
    mock_job.PENDING = "PENDING"
    mock_job.RUNNING = "RUNNING"
    mock_job.config = None
    mock_job.compute_profile = None
    mock_job.program.image = None
    mock_job.program.artifact = None
    mock_job.program.entrypoint = "main.py"

    runner = FleetsRunner(mock_job)
    mock_handler = MagicMock()
    runner._handler = mock_handler  # pylint: disable=protected-access

    mock_project = MagicMock()
    mock_project.subnet_pool_id = "subnet-1"
    mock_project.pds_name_state = "state-pds"
    mock_project.project_name = "test-project"
    mock_project.cos_bucket_user_data_name = None
    mock_project.cos_bucket_provider_data_name = None
    mock_project.cos_instance_name = None
    mock_project.cos_key_name = None
    runner._project = mock_project  # pylint: disable=protected-access
    runner._connected = True  # pylint: disable=protected-access

    mock_fleet = MagicMock()
    mock_fleet.to_dict.return_value = {"id": "fleet-abc"}
    mock_handler.submit_job.return_value = mock_fleet

    return runner, mock_handler


def _make_logs_runner() -> tuple[FleetsRunner, MagicMock]:
    """Build a FleetsRunner pre-wired for logs()/provider_logs() tests.

    Returns:
        Tuple of ``(runner, mock_handler)`` with COS fully configured.
    """
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    runner.job.author.id = "user-42"
    runner.job.program.provider = None
    runner.job.program.title = "my-program"
    runner.job.id = "job-uuid"

    runner._project.cos_bucket_user_data_name = "user-bucket"  # pylint: disable=protected-access
    runner._project.cos_bucket_provider_data_name = "provider-bucket"  # pylint: disable=protected-access
    runner._project.cos_instance_name = "cos-instance"  # pylint: disable=protected-access
    runner._project.cos_key_name = "cos-key"  # pylint: disable=protected-access

    return runner, mock_handler


def test_is_active_true_when_fleet_exists():
    """is_active() returns True when CE API confirms fleet exists."""
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    mock_handler.get_job_status.return_value = {"status": "running"}
    assert runner.is_active() is True
    mock_handler.get_job_status.assert_called_once_with("fleet-123")


def test_is_active_false_when_no_fleet_id():
    """is_active() returns False when job.fleet_id is None."""
    runner, _ = _make_runner(fleet_id=None)
    assert runner.is_active() is False


def test_is_active_false_when_fleet_not_found():
    """is_active() returns False when CE API returns 404."""
    runner, mock_handler = _make_runner(fleet_id="fleet-gone")
    mock_handler.get_job_status.side_effect = ApiException(status=404, reason="Not Found")
    assert runner.is_active() is False


def test_is_active_false_on_connection_error():
    """is_active() returns False when connection to CE fails."""
    runner, _ = _make_runner(fleet_id="fleet-123")
    runner._connected = False  # pylint: disable=protected-access
    runner._handler = None  # pylint: disable=protected-access
    with patch.object(runner, "connect", side_effect=Exception("connection failed")):
        assert runner.is_active() is False


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("pending", "PENDING"),
        ("running", "RUNNING"),
        ("succeeded", "SUCCEEDED"),
        ("successful", "SUCCEEDED"),
        ("failed", "FAILED"),
        ("stopped", "STOPPED"),
        ("cancelled", "STOPPED"),
        ("canceled", "STOPPED"),
        ("canceling", "STOPPED"),
        ("unknown-status", "PENDING"),
    ],
)
def test_status_maps_fleet_status(raw, expected):
    """status() maps CE fleet statuses to Job.STATUS constants correctly."""
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    mock_handler.get_job_status.return_value = {"status": raw}

    result = runner.status()

    assert result == getattr(runner.job, expected)


def test_status_returns_none_on_429():
    """status() returns None on 429 to allow scheduler retry without failing the job."""
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    mock_handler.get_job_status.side_effect = ApiException(status=429, reason="Too Many Requests")

    result = runner.status()

    assert result is None


def test_status_raises_runner_error_on_other_api_exception():
    """status() raises RunnerError on non-429 ApiException."""
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    mock_handler.get_job_status.side_effect = ApiException(status=500, reason="Internal Error")

    with pytest.raises(RunnerError):
        runner.status()


def test_status_raises_runner_error_when_no_fleet_id():
    """status() raises RunnerError when job has no fleet_id."""
    runner, _ = _make_runner(fleet_id=None)

    with pytest.raises(RunnerError, match="fleet_id"):
        runner.status()


def test_stop_deletes_fleet_when_running():
    """stop() calls delete_job when fleet is in running state."""
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    mock_handler.get_job_status.return_value = {"status": "running"}

    result = runner.stop()

    assert result is True
    mock_handler.cancel_job.assert_called_once_with("fleet-123", wait=False, delete=False)


def test_stop_returns_false_when_already_terminal():
    """stop() returns False without calling cancel_job when fleet is already terminal."""
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    mock_handler.get_job_status.return_value = {"status": "succeeded"}

    result = runner.stop()

    assert result is False
    mock_handler.cancel_job.assert_not_called()


def test_build_cos_paths_structure():
    """_build_cos_paths() produces the expected COS key structure.

    Verifies that user/provider function prefixes and job-level paths follow
    the convention used by fleets_runner._build_cos_paths() and expected by
    the entrypoint running inside the container.
    """
    runner, _ = _make_runner()
    runner.job.author.id = "user-42"
    runner.job.program.provider = None  # custom function -> provider_name = "default"
    runner.job.program.title = "my-program"
    runner.job.id = "job-uuid"

    paths = runner._build_cos_paths()  # pylint: disable=protected-access

    assert paths["user_function_prefix"] == "users/user-42/provider_functions/default/my-program"
    assert paths["provider_function_prefix"] == "providers/default/my-program"
    assert paths["user_job_prefix"] == "users/user-42/provider_functions/default/my-program/jobs/job-uuid"
    assert paths["user_log_key"].endswith("/logs.log")
    assert paths["provider_log_key"].endswith("/logs.log")
    assert paths["user_arguments_key"].endswith("/arguments.json")
    assert paths["user_mount_path"] == "/data"
    assert paths["provider_mount_path"] == "/function_data"


def test_submit_sets_fleet_id_without_cos():
    """submit() sets job.fleet_id when COS is not configured."""
    runner, mock_handler = _make_submit_runner()

    with _patch_settings():
        runner.submit()

    assert runner.job.fleet_id == "fleet-abc"
    mock_handler.submit_job.assert_called_once()


def test_submit_raises_runner_error_on_api_exception():
    """submit() raises RunnerError when the fleet API returns an error."""
    runner, mock_handler = _make_submit_runner()
    mock_handler.submit_job.side_effect = ApiException(status=400, reason="Bad Request")

    with _patch_settings():
        with pytest.raises(RunnerError):
            runner.submit()


def test_submit_raises_runner_error_when_no_fleet_id_returned():
    """submit() raises RunnerError when API returns no fleet ID."""
    runner, mock_handler = _make_submit_runner()
    mock_fleet = MagicMock()
    mock_fleet.to_dict.return_value = {"id": None}
    mock_handler.submit_job.return_value = mock_fleet

    with _patch_settings():
        with pytest.raises(RunnerError, match="fleet ID"):
            runner.submit()


def test_submit_parses_compute_profile_with_gpu():
    """submit() parses compute_profile into cpu, memory, and gpu."""
    runner, mock_handler = _make_submit_runner()
    runner.job.compute_profile = "gx3d-24x120x1a100p"

    with _patch_settings():
        runner.submit()

    call_kwargs = mock_handler.submit_job.call_args.kwargs
    assert call_kwargs["scale_cpu_limit"] == "24"
    assert call_kwargs["scale_memory_limit"] == "120G"
    assert call_kwargs["extra_fields"]["scale_gpu"] == {"preferences": [{"family": "a100p", "allocation": "1"}]}


def test_submit_parses_compute_profile_without_prefix():
    """submit() parses profiles without a prefix like '24x120x2a100p'."""
    runner, mock_handler = _make_submit_runner()
    runner.job.compute_profile = "24x120x2a100p"

    with _patch_settings():
        runner.submit()

    call_kwargs = mock_handler.submit_job.call_args.kwargs
    assert call_kwargs["scale_cpu_limit"] == "24"
    assert call_kwargs["scale_memory_limit"] == "120G"
    assert call_kwargs["extra_fields"]["scale_gpu"] == {"preferences": [{"family": "a100p", "allocation": "2"}]}


def test_submit_parses_compute_profile_without_gpu():
    """submit() parses a CPU-only profile correctly."""
    runner, mock_handler = _make_submit_runner()
    runner.job.compute_profile = "cx3d-4x16"

    with _patch_settings():
        runner.submit()

    call_kwargs = mock_handler.submit_job.call_args.kwargs
    assert call_kwargs["scale_cpu_limit"] == "4"
    assert call_kwargs["scale_memory_limit"] == "16G"
    assert call_kwargs.get("extra_fields") is None


def test_submit_uses_default_profile_when_no_compute_profile():
    """submit() uses DEFAULT_COMPUTE_PROFILE when job has no compute_profile."""
    runner, mock_handler = _make_submit_runner()

    with _patch_settings(DEFAULT_COMPUTE_PROFILE="cx3d-8x32"):
        runner.submit()

    call_kwargs = mock_handler.submit_job.call_args.kwargs
    assert call_kwargs["scale_cpu_limit"] == "8"
    assert call_kwargs["scale_memory_limit"] == "32G"


def test_submit_uses_program_image():
    """submit() uses program.image when set."""
    runner, mock_handler = _make_submit_runner()
    runner.job.program.image = "custom-image:latest"

    with _patch_settings():
        runner.submit()

    assert mock_handler.submit_job.call_args.kwargs["image_reference"] == "custom-image:latest"


def test_submit_uses_settings_default_image_when_no_program_image():
    """submit() falls back to FLEETS_DEFAULT_IMAGE when program has no image."""
    runner, mock_handler = _make_submit_runner()

    with _patch_settings(FLEETS_DEFAULT_IMAGE="fallback-image:v2"):
        runner.submit()

    assert mock_handler.submit_job.call_args.kwargs["image_reference"] == "fallback-image:v2"


def test_submit_uses_config_workers_as_max_instances():
    """submit() uses job.config.workers as scale_max_instances when set."""
    runner, mock_handler = _make_submit_runner()
    runner.job.config = MagicMock()
    runner.job.config.workers = 3

    with _patch_settings():
        runner.submit()

    assert mock_handler.submit_job.call_args.kwargs["scale_max_instances"] == 3


def test_submit_uses_settings_max_instances_when_no_config():
    """submit() falls back to FLEETS_DEFAULT_MAX_INSTANCES when config has no workers."""
    runner, mock_handler = _make_submit_runner()

    with _patch_settings(FLEETS_DEFAULT_MAX_INSTANCES=5):
        runner.submit()

    assert mock_handler.submit_job.call_args.kwargs["scale_max_instances"] == 5


def test_logs_returns_content_from_cos():
    """logs() retrieves user logs from the COS user bucket."""
    runner, mock_handler = _make_logs_runner()
    mock_handler.cos.logs.return_value = "log content"

    result = runner.logs()

    assert result == "log content"
    call_kwargs = mock_handler.cos.logs.call_args.kwargs
    assert call_kwargs["bucket_name"] == "user-bucket"
    assert call_kwargs["log_key"].endswith("/logs.log")


def test_provider_logs_returns_content_from_cos():
    """provider_logs() retrieves provider logs from the COS provider bucket."""
    runner, mock_handler = _make_logs_runner()
    mock_handler.cos.logs.return_value = "provider log"

    result = runner.provider_logs()

    assert result == "provider log"
    call_kwargs = mock_handler.cos.logs.call_args.kwargs
    assert call_kwargs["bucket_name"] == "provider-bucket"
    assert call_kwargs["log_key"].endswith("/logs.log")


def test_logs_returns_not_configured_when_cos_missing():
    """logs() returns a message when COS is not configured."""
    runner, _ = _make_runner(fleet_id="fleet-123")
    runner._project.cos_bucket_user_data_name = None  # pylint: disable=protected-access
    runner._project.cos_bucket_provider_data_name = None  # pylint: disable=protected-access
    runner._project.cos_instance_name = None  # pylint: disable=protected-access
    runner._project.cos_key_name = None  # pylint: disable=protected-access

    result = runner.logs()

    assert "not configured" in result


def test_logs_raises_runner_error_on_api_exception():
    """logs() raises RunnerError when COS returns an API error."""
    runner, mock_handler = _make_logs_runner()
    mock_handler.cos.logs.side_effect = ApiException(status=403, reason="Forbidden")

    with pytest.raises(RunnerError):
        runner.logs()


def test_get_result_from_cos_returns_none_when_cos_not_configured():
    """get_result_from_cos() returns None when COS is not configured."""
    runner, _ = _make_runner(fleet_id="fleet-123")

    with patch.object(runner, "_is_cos_configured", return_value=False):
        result = runner.get_result_from_cos()

    assert result is None


def test_get_result_from_cos_returns_json_string():
    """get_result_from_cos() returns decoded results.json from COS."""
    runner, mock_handler = _make_runner(fleet_id="fleet-123")

    mock_handler.cos.get_object_bytes.return_value = b'{"status": "ok"}'
    runner._project.cos_bucket_user_data_name = "user-bucket"  # pylint: disable=protected-access

    with patch.object(runner, "_is_cos_configured", return_value=True), patch.object(
        runner, "_get_fleet_name", return_value="fleet-name"
    ), patch.object(
        runner,
        "_build_cos_paths",
        return_value={
            "user_job_prefix": "users/1/provider_functions/p/t/jobs/j",
            "user_function_prefix": "users/1/provider_functions/p/t",
            "provider_function_prefix": "providers/p/t",
        },
    ):
        result = runner.get_result_from_cos()

    assert result == '{"status": "ok"}'


def test_get_result_from_cos_returns_none_on_exception():
    """get_result_from_cos() returns None when COS retrieval fails."""
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    runner._project.cos_bucket_user_data_name = "user-bucket"  # pylint: disable=protected-access
    mock_handler.cos.get_object_bytes.side_effect = RuntimeError("COS error")

    with patch.object(runner, "_is_cos_configured", return_value=True), patch.object(
        runner, "_get_fleet_name", return_value="fleet-name"
    ), patch.object(runner, "_build_cos_paths", return_value={"user_job_prefix": "u/jobs/j"}):
        result = runner.get_result_from_cos()

    assert result is None


@pytest.mark.parametrize("active,raises", [(True, False), (False, True)])
def test_get_or_assign_project_existing(active, raises):
    """_get_or_assign_project() reuses an assigned active project; raises if inactive."""
    runner, _ = _make_runner()
    mock_project = MagicMock()
    mock_project.active = active
    mock_project.project_name = "my-project"
    runner.job.code_engine_project = mock_project

    with patch(f"{_RUNNER_MOD}.CodeEngineProject") as mock_ce:
        if raises:
            with pytest.raises(RunnerError):
                runner._get_or_assign_project()  # pylint: disable=protected-access
        else:
            assert runner._get_or_assign_project() is mock_project  # pylint: disable=protected-access
    mock_ce.objects.filter.assert_not_called()


@pytest.mark.parametrize(
    "zone_map,profile,expect_zone_filter",
    [
        ({"gx2-8x64x1l40s": "us-east-1"}, "gx2-8x64x1l40s", "us-east-1"),  # zone match
        ({}, "cx3d-4x16", None),  # profile not in map → fallback
        ({"cx3d-4x16": "any"}, "cx3d-4x16", None),  # "any" → fallback
    ],
)
def test_get_or_assign_project_zone_routing(zone_map, profile, expect_zone_filter):
    """_get_or_assign_project() routes to zone-specific or multi-zone project correctly."""
    runner, _ = _make_runner()
    runner.job.code_engine_project = None
    runner.job.compute_profile = profile
    runner.job.id = "job-uuid"
    mock_project = MagicMock()
    mock_qs = MagicMock()
    mock_qs.filter.return_value.first.return_value = mock_project

    with patch(f"{_RUNNER_MOD}.settings") as mock_settings, patch(f"{_RUNNER_MOD}.CodeEngineProject") as mock_ce:
        mock_settings.FLEETS_PROFILE_ZONE_MAP = zone_map
        mock_ce.objects.filter.return_value = mock_qs
        result = runner._get_or_assign_project()  # pylint: disable=protected-access

    assert result is mock_project
    if expect_zone_filter:
        mock_qs.filter.assert_called_once_with(zone=expect_zone_filter)
    else:
        mock_qs.filter.assert_any_call(zone__isnull=True)


@pytest.mark.parametrize(
    "zone_map,profile,none_qs,match",
    [
        ({"gx2-8x64x1l40s": "us-east-1"}, "gx2-8x64x1l40s", False, "us-east-1"),
        ({}, None, True, "No active Code Engine project"),
    ],
)
def test_get_or_assign_project_raises(zone_map, profile, none_qs, match):
    """_get_or_assign_project() raises RunnerError when no suitable project is found."""
    runner, _ = _make_runner()
    runner.job.code_engine_project = None
    runner.job.compute_profile = profile
    runner.job.id = "job-uuid"
    mock_qs = MagicMock()
    mock_qs.filter.return_value.first.return_value = None
    if none_qs:
        mock_qs.first.return_value = None

    with patch(f"{_RUNNER_MOD}.settings") as mock_settings, patch(f"{_RUNNER_MOD}.CodeEngineProject") as mock_ce:
        mock_settings.FLEETS_PROFILE_ZONE_MAP = zone_map
        mock_ce.objects.filter.return_value = mock_qs
        with pytest.raises(RunnerError, match=match):
            runner._get_or_assign_project()  # pylint: disable=protected-access


def test_get_handler_cos_config_secret_name():
    """_get_handler_cos_config() returns hmac_secret_name when CE_HMAC_SECRET_NAME is set."""
    runner, _ = _make_runner()
    runner._project.cos_instance_name = "my-cos"  # pylint: disable=protected-access
    runner._project.cos_key_name = "my-key"  # pylint: disable=protected-access
    runner._project.region = "us-east"  # pylint: disable=protected-access

    with patch(f"{_RUNNER_MOD}.settings") as mock_settings:
        mock_settings.CE_HMAC_SECRET_NAME = "cos-hmac-secret"
        mock_settings.CE_COS_USE_PUBLIC_ENDPOINT = False
        config = runner._get_handler_cos_config()  # pylint: disable=protected-access

    assert config["hmac_secret_name"] == "cos-hmac-secret"
    assert config["bucket_region"] == "us-east"
    assert len(config) == 2


def test_get_handler_cos_config_returns_none_when_no_credentials():
    """_get_handler_cos_config() returns None when CE_HMAC_SECRET_NAME is not configured."""
    runner, _ = _make_runner()
    runner._project.cos_instance_name = "my-cos"  # pylint: disable=protected-access
    runner._project.cos_key_name = "my-key"  # pylint: disable=protected-access
    runner._project.region = "us-east"  # pylint: disable=protected-access

    with patch(f"{_RUNNER_MOD}.settings") as mock_settings:
        mock_settings.CE_HMAC_SECRET_NAME = None
        config = runner._get_handler_cos_config()  # pylint: disable=protected-access

    assert config is None


def test_get_handler_cos_config_includes_public_endpoint_when_flag_set():
    """_get_handler_cos_config() sets public cos_endpoint_url when CE_COS_USE_PUBLIC_ENDPOINT is True."""
    runner, _ = _make_runner()
    runner._project.region = "us-east"  # pylint: disable=protected-access

    with patch(f"{_RUNNER_MOD}.settings") as mock_settings:
        mock_settings.CE_HMAC_SECRET_NAME = "cos-hmac-secret"
        mock_settings.CE_COS_USE_PUBLIC_ENDPOINT = True
        config = runner._get_handler_cos_config()  # pylint: disable=protected-access

    assert config["cos_endpoint_url"] == "https://s3.us-east.cloud-object-storage.appdomain.cloud"


def test_get_handler_cos_config_omits_endpoint_url_by_default():
    """_get_handler_cos_config() omits cos_endpoint_url when CE_COS_USE_PUBLIC_ENDPOINT is False (private default)."""
    runner, _ = _make_runner()
    runner._project.region = "us-east"  # pylint: disable=protected-access

    with patch(f"{_RUNNER_MOD}.settings") as mock_settings:
        mock_settings.CE_HMAC_SECRET_NAME = "cos-hmac-secret"
        mock_settings.CE_COS_USE_PUBLIC_ENDPOINT = False
        config = runner._get_handler_cos_config()  # pylint: disable=protected-access

    assert "cos_endpoint_url" not in config


def test_connect_skips_when_already_connected():
    """connect() returns immediately if already connected."""
    runner, mock_handler = _make_runner()
    runner._connected = True  # pylint: disable=protected-access
    runner._handler = mock_handler  # pylint: disable=protected-access

    runner.connect()

    mock_handler.submit_job.assert_not_called()


def test_connect_raises_runner_error_on_failure():
    """connect() raises RunnerError when _get_handler fails."""
    runner, _ = _make_runner()
    runner._connected = False  # pylint: disable=protected-access
    runner._handler = None  # pylint: disable=protected-access

    with patch.object(runner, "_get_handler", side_effect=RuntimeError("connection failed")):
        with pytest.raises(RunnerError, match="connect"):
            runner.connect()


def test_is_cos_configured_true_when_all_fields_set():
    """_is_cos_configured() returns True when all four COS fields are set."""
    runner, _ = _make_runner()
    runner._project.cos_bucket_user_data_name = "u"  # pylint: disable=protected-access
    runner._project.cos_bucket_provider_data_name = "p"  # pylint: disable=protected-access
    runner._project.cos_instance_name = "i"  # pylint: disable=protected-access
    runner._project.cos_key_name = "k"  # pylint: disable=protected-access

    assert runner._is_cos_configured() is True  # pylint: disable=protected-access


def test_is_cos_configured_false_when_project_missing():
    """_is_cos_configured() returns False when _project is None."""
    runner, _ = _make_runner()
    runner._project = None  # pylint: disable=protected-access

    assert runner._is_cos_configured() is False  # pylint: disable=protected-access


def test_get_api_key_returns_from_settings():
    """_get_api_key() returns IBM_CLOUD_API_KEY from settings."""
    runner, _ = _make_runner()

    with patch(f"{_RUNNER_MOD}.settings") as mock_settings:
        mock_settings.IBM_CLOUD_API_KEY = "my-api-key"
        result = runner._get_api_key()  # pylint: disable=protected-access

    assert result == "my-api-key"


def test_get_api_key_raises_when_not_configured():
    """_get_api_key() raises RunnerError when no API key is configured."""
    runner, _ = _make_runner()

    with patch(f"{_RUNNER_MOD}.settings") as mock_settings:
        mock_settings.IBM_CLOUD_API_KEY = None
        with pytest.raises(RunnerError, match="IBM_CLOUD_API_KEY"):
            runner._get_api_key()  # pylint: disable=protected-access


def test_get_fleet_name_returns_from_api():
    """_get_fleet_name() returns the fleet name from get_job_status."""
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    mock_handler.get_job_status.return_value = {"name": "job-xyz-123", "status": "running"}

    result = runner._get_fleet_name()  # pylint: disable=protected-access

    assert result == "job-xyz-123"


def test_get_fleet_name_falls_back_on_exception():
    """_get_fleet_name() falls back to job-{id} when API call fails."""
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    runner.job.id = "job-uuid"
    mock_handler.get_job_status.side_effect = RuntimeError("API error")

    result = runner._get_fleet_name()  # pylint: disable=protected-access

    assert result == "job-job-uuid"


def test_upload_arguments_to_cos_uploads_json():
    """_upload_arguments_to_cos() reads ArgumentsStorage and uploads to COS."""
    runner, mock_handler = _make_runner()
    runner._project.cos_bucket_user_data_name = "user-bucket"  # pylint: disable=protected-access
    runner.job.program.provider = None
    runner.job.author.username = "testuser"

    paths = {"user_arguments_key": "users/1/jobs/j/arguments.json"}

    with patch(f"{_RUNNER_MOD}.ArgumentsStorage") as mock_storage_cls:
        mock_storage_cls.return_value.get.return_value = '{"backend_name": "ibm_sherbrooke"}'
        runner._upload_arguments_to_cos(mock_handler, paths)  # pylint: disable=protected-access

    mock_handler.cos.upload_fileobj.assert_called_once()
    call_kwargs = mock_handler.cos.upload_fileobj.call_args.kwargs
    assert call_kwargs["bucket_name"] == "user-bucket"
    assert call_kwargs["key"] == "users/1/jobs/j/arguments.json"


def test_build_gateway_env_vars_returns_formatted_list():
    """_build_gateway_env_vars() returns env vars formatted for Code Engine."""
    runner, _ = _make_runner()
    runner.job.env_vars = '{"KEY1": "val1", "KEY2": "val2"}'

    with patch(f"{_RUNNER_MOD}.decrypt_env_vars", side_effect=lambda e: e):
        result = runner._build_gateway_env_vars()  # pylint: disable=protected-access

    assert result == [
        {"type": "literal", "name": "KEY1", "value": "val1"},
        {"type": "literal", "name": "KEY2", "value": "val2"},
    ]


def test_build_gateway_env_vars_decrypts_tokens():
    """_build_gateway_env_vars() passes env vars through decrypt_env_vars."""
    runner, _ = _make_runner()
    runner.job.env_vars = '{"QISKIT_IBM_TOKEN": "encrypted", "SOME_URL": "http://example.com"}'

    decrypted = {"QISKIT_IBM_TOKEN": "decrypted", "SOME_URL": "http://example.com"}
    with patch(f"{_RUNNER_MOD}.decrypt_env_vars", return_value=decrypted) as mock_decrypt:
        result = runner._build_gateway_env_vars()  # pylint: disable=protected-access

    mock_decrypt.assert_called_once_with({"QISKIT_IBM_TOKEN": "encrypted", "SOME_URL": "http://example.com"})
    assert {"type": "literal", "name": "QISKIT_IBM_TOKEN", "value": "decrypted"} in result
    assert {"type": "literal", "name": "SOME_URL", "value": "http://example.com"} in result


def test_build_gateway_env_vars_filters_empty_values():
    """_build_gateway_env_vars() excludes entries with empty or None values."""
    runner, _ = _make_runner()
    runner.job.env_vars = '{"KEEP": "value", "EMPTY": "", "NULL_VAL": null}'

    def passthrough(e):
        return e

    with patch(f"{_RUNNER_MOD}.decrypt_env_vars", side_effect=passthrough):
        result = runner._build_gateway_env_vars()  # pylint: disable=protected-access

    assert result == [{"type": "literal", "name": "KEEP", "value": "value"}]


def test_build_gateway_env_vars_empty_env_vars():
    """_build_gateway_env_vars() returns an empty list when job has no env vars."""
    runner, _ = _make_runner()
    runner.job.env_vars = "{}"

    with patch(f"{_RUNNER_MOD}.decrypt_env_vars", return_value={}):
        result = runner._build_gateway_env_vars()  # pylint: disable=protected-access

    assert result == []


def test_submit_includes_gateway_env_vars():
    """submit() includes decrypted gateway env vars in the run_env_variables."""
    runner, mock_handler = _make_submit_runner()
    runner.job.env_vars = '{"MY_TOKEN": "secret", "MY_URL": "http://example.com"}'
    runner.job.author.id = "user-1"
    runner.job.program.provider = None
    runner.job.program.title = "prog"

    runner._project.cos_bucket_user_data_name = "user-bucket"  # pylint: disable=protected-access
    runner._project.cos_bucket_provider_data_name = "prov-bucket"  # pylint: disable=protected-access
    runner._project.cos_instance_name = "cos-inst"  # pylint: disable=protected-access
    runner._project.cos_key_name = "cos-key"  # pylint: disable=protected-access
    runner._project.pds_name_users = "pds-users"  # pylint: disable=protected-access
    runner._project.pds_name_providers = "pds-provs"  # pylint: disable=protected-access

    decrypted = {"MY_TOKEN": "decrypted_secret", "MY_URL": "http://example.com"}
    with _patch_settings(), patch(f"{_RUNNER_MOD}.decrypt_env_vars", return_value=decrypted):
        runner.submit()

    call_kwargs = mock_handler.submit_job.call_args.kwargs
    env_list = call_kwargs["extra_fields"]["run_env_variables"]
    assert {"type": "literal", "name": "MY_TOKEN", "value": "decrypted_secret"} in env_list
    assert {"type": "literal", "name": "MY_URL", "value": "http://example.com"} in env_list
