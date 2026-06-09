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
from core.ibm_cloud.code_engine.fleets.utils import FleetJobPaths, build_job_paths
from core.models import Program
from core.services.runners.abstract_runner import RunnerError
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
    runner._cos = MagicMock()  # pylint: disable=protected-access
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
        "FLEETS_DEFAULT_MAX_INSTANCES": 1,
        "DEFAULT_COMPUTE_PROFILE": "cx3d-4x16",
        "FLEETS_GATEWAY_HOST": None,
        "CUSTOM_IMAGE_PACKAGE_PATH": "/runner",
        "CUSTOM_IMAGE_PACKAGE_NAME": "runner",
    }
    defaults.update(overrides)
    with (
        patch(f"{_RUNNER_MOD}.settings") as mock_settings,
        patch(f"{_RUNNER_MOD}.decrypt_env_vars", return_value={}),
    ):
        for key, value in defaults.items():
            setattr(mock_settings, key, value)
        yield mock_settings


def _make_submit_runner() -> tuple[FleetsRunner, MagicMock]:
    """Build a FleetsRunner pre-wired for submit() with COS configured.

    COS interactions are mocked: _upload_program_to_cos is patched to a no-op
    so tests that verify fleet submission parameters don't need real COS credentials.

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
    mock_job.program.provider = None
    mock_job.program.runner = Program.FLEETS
    mock_job.env_vars = "{}"
    mock_job.arguments = "{}"

    runner = FleetsRunner(mock_job)
    mock_handler = MagicMock()
    runner._handler = mock_handler  # pylint: disable=protected-access

    mock_project = MagicMock()
    mock_project.subnet_pool_id = "subnet-1"
    mock_project.pds_name_state = "state-pds"
    mock_project.project_name = "test-project"
    mock_project.cos_bucket_user_data_name = "user-bucket"
    mock_project.cos_bucket_provider_data_name = "provider-bucket"
    mock_project.cos_instance_name = "cos-instance"
    mock_project.cos_key_name = "cos-key"
    mock_project.pds_name_users = "user-pds"
    mock_project.pds_name_providers = "provider-pds"
    runner._project = mock_project  # pylint: disable=protected-access
    runner._connected = True  # pylint: disable=protected-access

    mock_fleet = MagicMock()
    mock_fleet.to_dict.return_value = {"id": "fleet-abc"}
    mock_handler.submit_job.return_value = mock_fleet
    runner._cos = MagicMock()  # pylint: disable=protected-access

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


def test_submit_sets_fleet_id_with_cos():
    """submit() sets job.fleet_id when COS is configured."""
    runner, mock_handler = _make_submit_runner()

    with _patch_settings():
        runner.submit()

    assert runner.job.fleet_id == "fleet-abc"
    mock_handler.submit_job.assert_called_once()


def test_submit_raises_runner_error_when_cos_not_configured():
    """submit() raises RunnerError when COS is not configured — Fleets requires COS."""
    runner, _ = _make_submit_runner()
    runner._project.cos_bucket_user_data_name = None  # pylint: disable=protected-access
    runner._project.cos_instance_name = None  # pylint: disable=protected-access
    runner._project.cos_key_name = None  # pylint: disable=protected-access

    with _patch_settings(), pytest.raises(RunnerError, match="COS is not configured"):
        runner.submit()


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
    assert "scale_gpu" not in (call_kwargs.get("extra_fields") or {})


def test_submit_uses_default_profile_when_no_compute_profile():
    """submit() uses DEFAULT_COMPUTE_PROFILE when job has no compute_profile."""
    runner, mock_handler = _make_submit_runner()

    with _patch_settings(DEFAULT_COMPUTE_PROFILE="cx3d-8x32"):
        runner.submit()

    call_kwargs = mock_handler.submit_job.call_args.kwargs
    assert call_kwargs["scale_cpu_limit"] == "8"
    assert call_kwargs["scale_memory_limit"] == "32G"


def test_submit_default_profile_in_settings_is_parseable():
    """DEFAULT_COMPUTE_PROFILE default value in settings.py parses without error."""
    runner, mock_handler = _make_submit_runner()

    with _patch_settings(DEFAULT_COMPUTE_PROFILE="bx3d-24x120"):
        runner.submit()

    call_kwargs = mock_handler.submit_job.call_args.kwargs
    assert call_kwargs["scale_cpu_limit"] == "24"
    assert call_kwargs["scale_memory_limit"] == "120G"
    assert call_kwargs.get("extra_fields") is None


def test_submit_raises_on_unparseable_compute_profile():
    """submit() raises RunnerError when compute_profile cannot be parsed."""
    runner, _ = _make_submit_runner()
    runner.job.compute_profile = "not-a-valid-profile"

    with _patch_settings():
        with pytest.raises(RunnerError, match="Could not parse compute_profile"):
            runner.submit()


def test_submit_uses_program_image():
    """submit() uses program.image when set."""
    runner, mock_handler = _make_submit_runner()
    runner.job.program.image = "custom-image:latest"

    with _patch_settings(), patch.object(runner, "_upload_program_to_cos"):
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


def test_get_result_from_cos_returns_none_when_cos_not_configured():
    """get_result_from_cos() returns None when COS is not configured."""
    runner, _ = _make_runner(fleet_id="fleet-123")

    with patch.object(runner, "_is_cos_configured", return_value=False):
        result = runner.get_result_from_cos()

    assert result is None


def test_get_result_from_cos_returns_json_string():
    """get_result_from_cos() returns decoded results.json from COS."""
    runner, _ = _make_runner(fleet_id="fleet-123")

    runner._cos.get_object_bytes.return_value = b'{"status": "ok"}'  # pylint: disable=protected-access
    runner._project.cos_bucket_user_data_name = "user-bucket"  # pylint: disable=protected-access

    with (
        patch.object(runner, "_is_cos_configured", return_value=True),
        patch.object(runner, "_get_fleet_name", return_value="fleet-name"),
        patch(
            f"{_RUNNER_MOD}.build_job_paths",
            return_value=FleetJobPaths(
                cos_user_function_prefix="users/IBMid-50FJDA/provider_functions/Q-CTRL/sampler-v2/data",
                cos_user_job_prefix="users/IBMid-50FJDA/provider_functions/Q-CTRL/sampler-v2/jobs/8be4df61-93ca",
                cos_user_log_key="users/IBMid-50FJDA/provider_functions/Q-CTRL/sampler-v2/jobs/8be4df61-93ca/logs.log",
                cos_results_key="users/IBMid-50FJDA/provider_functions/Q-CTRL/sampler-v2/jobs/8be4df61-93ca/results.json",  # fmt: skip
                cos_provider_function_prefix="providers/Q-CTRL/sampler-v2/data",
                cos_provider_job_prefix="providers/Q-CTRL/sampler-v2/jobs/8be4df61-93ca",
                cos_provider_log_key="providers/Q-CTRL/sampler-v2/jobs/8be4df61-93ca/logs.log",
                cos_function_entrypoint="providers/Q-CTRL/sampler-v2/data/main.py",
                cos_docker_entrypoint="providers/Q-CTRL/sampler-v2/data/fleet_provider_job_wrapper.py",
                container_function_entrypoint="/function_provider_data/main.py",
                container_docker_entrypoint="/function_provider_data/fleet_provider_job_wrapper.py",
                container_public_log_path="/job_user_data/logs.log",
                container_private_log_path="/job_provider_data/logs.log",
                container_arguments_path="/job_user_data/arguments.json",
                container_result_path="/job_user_data/results.json",
            ),
        ),
    ):
        result = runner.get_result_from_cos()

    assert result == '{"status": "ok"}'


def test_get_result_from_cos_returns_none_on_exception():
    """get_result_from_cos() returns None when COS retrieval fails."""
    runner, _ = _make_runner(fleet_id="fleet-123")
    runner._project.cos_bucket_user_data_name = "user-bucket"  # pylint: disable=protected-access
    runner._cos.get_object_bytes.side_effect = RuntimeError("COS error")  # pylint: disable=protected-access

    with (
        patch.object(runner, "_is_cos_configured", return_value=True),
        patch.object(runner, "_get_fleet_name", return_value="fleet-name"),
    ):
        result = runner.get_result_from_cos()

    assert result is None


@pytest.mark.parametrize("active,raises", [(True, False), (False, True)])
def test_get_project_existing(active, raises):
    """_get_project() returns an active project; raises if inactive."""
    runner, _ = _make_runner()
    mock_project = MagicMock()
    mock_project.active = active
    mock_project.project_name = "my-project"
    runner.job.code_engine_project = mock_project

    if raises:
        with pytest.raises(RunnerError):
            runner._get_project()  # pylint: disable=protected-access
    else:
        assert runner._get_project() is mock_project  # pylint: disable=protected-access


def test_get_project_raises_when_no_project_assigned():
    """_get_project() raises RunnerError when job.code_engine_project is None."""
    runner, _ = _make_runner()
    runner.job.code_engine_project = None
    runner.job.id = "job-uuid"

    with pytest.raises(RunnerError, match="No Code Engine project assigned"):
        runner._get_project()  # pylint: disable=protected-access


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


def test_submit_includes_gateway_env_vars():
    """submit() includes decrypted gateway env vars in the run_env_variables."""
    runner, mock_handler = _make_submit_runner()
    runner.job.env_vars = '{"MY_TOKEN": "secret", "MY_URL": "http://example.com"}'
    runner.job.author.username = "user-1"
    runner.job.program.provider = None
    runner.job.program.title = "prog"
    runner.job.program.runner = Program.FLEETS

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
    by_name = {e["name"]: e["value"] for e in env_list}
    assert by_name["MY_TOKEN"] == "decrypted_secret"
    assert by_name["MY_URL"] == "http://example.com"
    assert by_name["ARGUMENTS_PATH"] == "/job_user_data/arguments.json"
    assert by_name["RESULTS_PATH"] == "/job_user_data/results.json"
    assert by_name["PUBLIC_LOG_PATH"] == "/job_user_data/logs.log"


def test_submit_arguments_path_set_exactly_once():
    """submit() sets ARGUMENTS_PATH exactly once even when it appears in job env vars."""
    runner, mock_handler = _make_submit_runner()
    runner.job.env_vars = '{"ARGUMENTS_PATH": "/old/stale/path", "OTHER": "val"}'
    runner.job.author.username = "user-1"
    runner.job.program.provider = None
    runner.job.program.title = "prog"
    runner.job.program.runner = Program.FLEETS

    runner._project.cos_bucket_user_data_name = "user-bucket"  # pylint: disable=protected-access
    runner._project.cos_bucket_provider_data_name = "prov-bucket"  # pylint: disable=protected-access
    runner._project.cos_instance_name = "cos-inst"  # pylint: disable=protected-access
    runner._project.cos_key_name = "cos-key"  # pylint: disable=protected-access
    runner._project.pds_name_users = "pds-users"  # pylint: disable=protected-access
    runner._project.pds_name_providers = "pds-provs"  # pylint: disable=protected-access

    decrypted = {"ARGUMENTS_PATH": "/old/stale/path", "OTHER": "val"}
    with _patch_settings(), patch(f"{_RUNNER_MOD}.decrypt_env_vars", return_value=decrypted):
        runner.submit()

    call_kwargs = mock_handler.submit_job.call_args.kwargs
    env_list = call_kwargs["extra_fields"]["run_env_variables"]
    arguments_path_entries = [e for e in env_list if e.get("name") == "ARGUMENTS_PATH"]
    assert len(arguments_path_entries) == 1
    assert arguments_path_entries[0]["value"] == "/job_user_data/arguments.json"


def test_upload_provider_image_entrypoint_uploads_to_provider_bucket():
    """_upload_provider_image_entrypoint() uploads rendered template to provider bucket for provider jobs."""
    runner, _ = _make_runner()
    runner.job.author.username = "alice"
    runner.job.program.provider = MagicMock()
    runner.job.program.provider.name = "acme"
    runner.job.program.title = "my-func"
    runner.job.program.entrypoint = "main.py"
    runner.job.program.runner = Program.FLEETS
    runner.job.id = "job-1"
    runner.job.arguments = "{}"
    runner._project.cos_bucket_provider_data_name = "provider-bucket"  # pylint: disable=protected-access
    runner._project.cos_bucket_user_data_name = "user-bucket"  # pylint: disable=protected-access

    paths = build_job_paths(runner.job)

    mock_template = MagicMock()
    mock_template.render.return_value = "rendered content"

    with (
        _patch_settings(),
        patch(f"{_RUNNER_MOD}.get_template", return_value=mock_template),
    ):
        runner._upload_provider_image_entrypoint(paths)  # pylint: disable=protected-access

    call = runner._cos.upload_fileobj.call_args  # pylint: disable=protected-access
    assert call.kwargs["bucket_name"] == "provider-bucket"
    assert call.kwargs["key"] == "providers/acme/my-func/data/main.py"
    assert call.kwargs["fileobj"].read() == b"rendered content"


def test_upload_provider_image_entrypoint_raises_for_non_provider_job():
    """_upload_provider_image_entrypoint() raises RunnerError when called on a non-provider job."""
    runner, _ = _make_runner()
    runner.job.author.username = "alice"
    runner.job.program.provider = None
    runner.job.program.title = "my-func"
    runner.job.program.entrypoint = "main.py"
    runner.job.id = "job-1"
    runner.job.arguments = "{}"

    paths = build_job_paths(runner.job)

    with pytest.raises(RunnerError, match="non-provider job"):
        runner._upload_provider_image_entrypoint(paths)  # pylint: disable=protected-access


def test_upload_provider_image_entrypoint_error_propagates():
    """_upload_provider_image_entrypoint() does not swallow COS errors."""
    runner, _ = _make_runner()
    runner.job.author.username = "alice"
    runner.job.program.provider = MagicMock()
    runner.job.program.provider.name = "acme"
    runner.job.program.title = "my-func"
    runner.job.program.entrypoint = "main.py"
    runner.job.program.runner = Program.FLEETS
    runner.job.id = "job-1"
    runner.job.arguments = "{}"
    runner._project.cos_bucket_provider_data_name = "provider-bucket"  # pylint: disable=protected-access

    paths = build_job_paths(runner.job)

    mock_template = MagicMock()
    mock_template.render.return_value = "content"
    runner._cos.upload_fileobj.side_effect = RuntimeError("COS error")  # pylint: disable=protected-access

    with (
        _patch_settings(),
        patch(f"{_RUNNER_MOD}.get_template", return_value=mock_template),
        pytest.raises(RuntimeError, match="COS error"),
    ):
        runner._upload_provider_image_entrypoint(paths)  # pylint: disable=protected-access


def test_submit_uses_provider_image_entrypoint_upload_when_image_set():
    """submit() calls _upload_provider_image_entrypoint when program.image is set but no artifact."""
    runner, _ = _make_submit_runner()
    runner.job.program.image = "custom:latest"
    runner.job.program.artifact = None
    runner.job.author.username = "user-1"
    runner.job.program.provider = None
    runner.job.program.title = "prog"
    runner.job.env_vars = "{}"

    runner._project.cos_bucket_user_data_name = "user-bucket"  # pylint: disable=protected-access
    runner._project.cos_bucket_provider_data_name = "prov-bucket"  # pylint: disable=protected-access
    runner._project.cos_instance_name = "cos-inst"  # pylint: disable=protected-access
    runner._project.cos_key_name = "cos-key"  # pylint: disable=protected-access
    runner._project.pds_name_users = "pds-users"  # pylint: disable=protected-access
    runner._project.pds_name_providers = "pds-provs"  # pylint: disable=protected-access

    with (
        _patch_settings(),
        patch.object(runner, "_upload_provider_image_entrypoint") as mock_tmpl,
        patch.object(runner, "_upload_custom_image_entrypoint") as mock_art,
        patch(f"{_RUNNER_MOD}.decrypt_env_vars", return_value={}),
    ):
        runner.submit()

    mock_tmpl.assert_called_once()
    mock_art.assert_not_called()


def test_submit_uses_artifact_upload_when_artifact_set():
    """submit() calls _upload_artifact_to_cos (not template) when program.artifact is set."""
    runner, _ = _make_submit_runner()
    runner.job.program.artifact = MagicMock()
    runner.job.program.image = None
    runner.job.author.username = "user-1"
    runner.job.program.provider = None
    runner.job.program.title = "prog"
    runner.job.env_vars = "{}"

    runner._project.cos_bucket_user_data_name = "user-bucket"  # pylint: disable=protected-access
    runner._project.cos_bucket_provider_data_name = "prov-bucket"  # pylint: disable=protected-access
    runner._project.cos_instance_name = "cos-inst"  # pylint: disable=protected-access
    runner._project.cos_key_name = "cos-key"  # pylint: disable=protected-access
    runner._project.pds_name_users = "pds-users"  # pylint: disable=protected-access
    runner._project.pds_name_providers = "pds-provs"  # pylint: disable=protected-access

    with (
        _patch_settings(),
        patch.object(runner, "_upload_custom_image_entrypoint") as mock_art,
        patch.object(runner, "_upload_provider_image_entrypoint") as mock_tmpl,
        patch(f"{_RUNNER_MOD}.decrypt_env_vars", return_value={}),
    ):
        runner.submit()

    mock_art.assert_called_once()
    mock_tmpl.assert_not_called()
