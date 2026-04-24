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

from unittest.mock import MagicMock, patch

import pytest
from core.ibm_cloud.code_engine.ce_client.rest import ApiException

from core.services.runners.fleets_runner import FleetsRunner

_RUNNER_MOD = "core.services.runners.fleets_runner"


# Helpers


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
    runner._project = MagicMock()
    runner._connected = True
    return runner, mock_handler


# is_active


def test_is_active_true_when_fleet_id_set():
    """is_active() returns True when job.fleet_id is set."""
    runner, _ = _make_runner(fleet_id="fleet-123")
    assert runner.is_active() is True


def test_is_active_false_when_no_fleet_id():
    """is_active() returns False when job.fleet_id is None."""
    runner, _ = _make_runner(fleet_id=None)
    assert runner.is_active() is False


# status


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
        ("canceling", "STOPPED"),
        ("unknown-status", "PENDING"),  # falls back to PENDING
    ],
)
def test_status_maps_fleet_status(raw, expected):
    """status() maps CE fleet statuses to Job.STATUS constants correctly.

    Args:
        raw: Raw CE fleet status string.
        expected: Expected Job.STATUS constant value.
    """
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
    from core.services.runners.abstract_runner import RunnerError  # pylint: disable=import-outside-toplevel

    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    mock_handler.get_job_status.side_effect = ApiException(status=500, reason="Internal Error")

    with pytest.raises(RunnerError):
        runner.status()


def test_status_raises_runner_error_when_no_fleet_id():
    """status() raises RunnerError when job has no fleet_id."""
    from core.services.runners.abstract_runner import RunnerError  # pylint: disable=import-outside-toplevel

    runner, _ = _make_runner(fleet_id=None)

    with pytest.raises(RunnerError, match="fleet_id"):
        runner.status()


# stop / free_resources


def test_stop_deletes_fleet_when_running():
    """stop() calls delete_job when fleet is in running state."""
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    mock_handler.get_job_status.return_value = {"status": "running"}

    result = runner.stop()

    assert result is True
    mock_handler.delete_job.assert_called_once_with("fleet-123")


def test_stop_returns_false_when_already_terminal():
    """stop() returns False without calling delete_job when fleet is already terminal."""
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    mock_handler.get_job_status.return_value = {"status": "succeeded"}

    result = runner.stop()

    assert result is False
    mock_handler.delete_job.assert_not_called()


def test_free_resources_calls_delete_job():
    """free_resources() calls delete_job on the handler."""
    runner, mock_handler = _make_runner(fleet_id="fleet-123")

    result = runner.free_resources()

    assert result is True
    mock_handler.delete_job.assert_called_once_with("fleet-123")


def test_free_resources_returns_false_when_no_fleet_id():
    """free_resources() returns False immediately when job has no fleet_id."""
    runner, mock_handler = _make_runner(fleet_id=None)

    result = runner.free_resources()

    assert result is False
    mock_handler.delete_job.assert_not_called()


# _build_cos_paths


def test_build_cos_paths_structure():
    """_build_cos_paths() produces the expected COS key structure.

    Verifies that user/provider function prefixes and job-level paths follow
    the convention used by fleets_runner._build_cos_paths() and expected by
    the entrypoint running inside the container.
    """
    runner, _ = _make_runner()
    runner.job.author.id = "user-42"
    runner.job.program.provider = None  # custom function → provider_name = "default"
    runner.job.program.title = "my-program"
    runner.job.id = "job-uuid"

    paths = runner._build_cos_paths("unused-fleet-name")  # pylint: disable=protected-access

    assert paths["user_function_prefix"] == "users/user-42/provider_functions/default/my-program"
    assert paths["provider_function_prefix"] == "providers/default/my-program"
    assert paths["user_job_prefix"] == "users/user-42/provider_functions/default/my-program/jobs/job-uuid"
    assert paths["user_log_key"].endswith("/logs.log")
    assert paths["provider_log_key"].endswith("/logs.log")
    assert paths["user_arguments_key"].endswith("/arguments.json")
    assert paths["user_mount_path"] == "/data"
    assert paths["provider_mount_path"] == "/function_data"


# _get_cpu_limit / _get_memory_limit


def test_get_cpu_limit_from_compute_profile():
    """_get_cpu_limit() parses CPU from compute_profile when set."""
    runner, _ = _make_runner()
    runner.job.compute_profile = "cx3d-4x16"

    assert runner._get_cpu_limit() == "4"  # pylint: disable=protected-access


def test_get_cpu_limit_falls_back_to_settings():
    """_get_cpu_limit() falls back to settings default when compute_profile is absent."""
    runner, _ = _make_runner()
    runner.job.compute_profile = None
    runner.job.config = None

    with patch(f"{_RUNNER_MOD}.settings") as mock_settings:
        mock_settings.FLEETS_DEFAULT_CPU_LIMIT = "2"
        result = runner._get_cpu_limit()  # pylint: disable=protected-access

    assert result == "2"


def test_get_memory_limit_from_compute_profile():
    """_get_memory_limit() parses memory from compute_profile when set."""
    runner, _ = _make_runner()
    runner.job.compute_profile = "cx3d-4x16"

    assert runner._get_memory_limit() == "16G"  # pylint: disable=protected-access


# _get_handler_cos_config


def test_get_handler_cos_config_secret_name():
    """_get_handler_cos_config() returns hmac_secret_name when CE_HMAC_SECRET_NAME is set."""
    runner, _ = _make_runner()
    runner._project.cos_instance_name = "my-cos"  # pylint: disable=protected-access
    runner._project.cos_key_name = "my-key"  # pylint: disable=protected-access
    runner._project.region = "us-east"  # pylint: disable=protected-access

    with patch(f"{_RUNNER_MOD}.settings") as mock_settings:
        mock_settings.CE_HMAC_SECRET_NAME = "cos-hmac-secret"
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

    with patch(f"{_RUNNER_MOD}.settings") as mock_settings, patch.dict(
        "os.environ", {}, clear=True
    ):
        mock_settings.CE_HMAC_SECRET_NAME = None
        config = runner._get_handler_cos_config()  # pylint: disable=protected-access

    assert config is None


# connect


def test_connect_skips_when_already_connected():
    """connect() returns immediately if already connected."""
    runner, mock_handler = _make_runner()
    runner._connected = True  # pylint: disable=protected-access
    runner._handler = mock_handler  # pylint: disable=protected-access

    runner.connect()

    # _get_handler should not be called again
    mock_handler.submit_job.assert_not_called()


def test_connect_raises_runner_error_on_failure():
    """connect() raises RunnerError when _get_handler fails."""
    from core.services.runners.abstract_runner import RunnerError  # pylint: disable=import-outside-toplevel

    runner, _ = _make_runner()
    runner._connected = False  # pylint: disable=protected-access
    runner._handler = None  # pylint: disable=protected-access

    with patch.object(runner, "_get_handler", side_effect=RuntimeError("connection failed")):
        with pytest.raises(RunnerError, match="connect"):
            runner.connect()


# submit


def test_submit_sets_fleet_id_without_cos():
    """submit() sets job.fleet_id when COS is not configured."""
    runner, mock_handler = _make_runner()
    runner._project.subnet_pool_id = "subnet-1"  # pylint: disable=protected-access
    runner._project.pds_name_state = "state-pds"  # pylint: disable=protected-access

    mock_fleet = MagicMock()
    mock_fleet.to_dict.return_value = {"id": "fleet-abc"}
    mock_handler.submit_job.return_value = mock_fleet

    with patch.object(runner, "_is_cos_configured", return_value=False), patch.object(
        runner, "_get_image", return_value="my-image"
    ), patch.object(runner, "_get_cpu_limit", return_value="1"), patch.object(
        runner, "_get_memory_limit", return_value="2G"
    ), patch.object(
        runner, "_get_gpu_config", return_value={}
    ):
        runner.submit()

    assert runner.job.fleet_id == "fleet-abc"
    mock_handler.submit_job.assert_called_once()


def test_submit_raises_runner_error_on_api_exception():
    """submit() raises RunnerError when the fleet API returns an error."""
    from core.services.runners.abstract_runner import RunnerError  # pylint: disable=import-outside-toplevel

    runner, mock_handler = _make_runner()
    runner._project.subnet_pool_id = "subnet-1"  # pylint: disable=protected-access
    runner._project.pds_name_state = "state-pds"  # pylint: disable=protected-access
    mock_handler.submit_job.side_effect = ApiException(status=400, reason="Bad Request")

    with patch.object(runner, "_is_cos_configured", return_value=False), patch.object(
        runner, "_get_image", return_value="my-image"
    ), patch.object(runner, "_get_cpu_limit", return_value="1"), patch.object(
        runner, "_get_memory_limit", return_value="2G"
    ), patch.object(
        runner, "_get_gpu_config", return_value={}
    ):
        with pytest.raises(RunnerError):
            runner.submit()


def test_submit_raises_runner_error_when_no_fleet_id_returned():
    """submit() raises RunnerError when API returns no fleet ID."""
    from core.services.runners.abstract_runner import RunnerError  # pylint: disable=import-outside-toplevel

    runner, mock_handler = _make_runner()
    runner._project.subnet_pool_id = "subnet-1"  # pylint: disable=protected-access
    runner._project.pds_name_state = "state-pds"  # pylint: disable=protected-access

    mock_fleet = MagicMock()
    mock_fleet.to_dict.return_value = {"id": None}
    mock_handler.submit_job.return_value = mock_fleet

    with patch.object(runner, "_is_cos_configured", return_value=False), patch.object(
        runner, "_get_image", return_value="my-image"
    ), patch.object(runner, "_get_cpu_limit", return_value="1"), patch.object(
        runner, "_get_memory_limit", return_value="2G"
    ), patch.object(
        runner, "_get_gpu_config", return_value={}
    ):
        with pytest.raises(RunnerError, match="fleet ID"):
            runner.submit()


# logs / provider_logs


def test_logs_delegates_to_get_logs_from_cos():
    """logs() calls _get_logs_from_cos with user bucket fields."""
    runner, _ = _make_runner(fleet_id="fleet-123")

    with patch.object(runner, "_get_logs_from_cos", return_value="log content") as mock_logs:
        result = runner.logs()

    assert result == "log content"
    mock_logs.assert_called_once_with(
        bucket_field="cos_bucket_user_data_name",
        log_key_field="user_log_key",
        label="user",
    )


def test_provider_logs_delegates_to_get_logs_from_cos():
    """provider_logs() calls _get_logs_from_cos with provider bucket fields."""
    runner, _ = _make_runner(fleet_id="fleet-123")

    with patch.object(runner, "_get_logs_from_cos", return_value="provider log") as mock_logs:
        result = runner.provider_logs()

    assert result == "provider log"
    mock_logs.assert_called_once_with(
        bucket_field="cos_bucket_provider_data_name",
        log_key_field="provider_log_key",
        label="provider",
    )


# get_result_from_cos


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
            "user_job_prefix": "users/1/jobs/j",
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


# _get_logs_from_cos


def test_get_logs_from_cos_returns_not_configured_message():
    """_get_logs_from_cos() returns a message when COS is not configured."""
    runner, _ = _make_runner(fleet_id="fleet-123")

    with patch.object(runner, "_is_cos_configured", return_value=False):
        result = runner._get_logs_from_cos(  # pylint: disable=protected-access
            bucket_field="cos_bucket_user_data_name", log_key_field="user_log_key", label="user"
        )

    assert "not configured" in result


def test_get_logs_from_cos_returns_log_content():
    """_get_logs_from_cos() retrieves and returns log content from COS."""
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    mock_handler.cos.logs.return_value = "log line 1\nlog line 2"
    runner._project.cos_bucket_user_data_name = "user-bucket"  # pylint: disable=protected-access

    with patch.object(runner, "_is_cos_configured", return_value=True), patch.object(
        runner, "_get_fleet_name", return_value="fleet-name"
    ), patch.object(
        runner,
        "_build_cos_paths",
        return_value={
            "user_log_key": "users/1/jobs/j/logs.log",
            "provider_log_key": "providers/p/jobs/j/logs.log",
        },
    ):
        result = runner._get_logs_from_cos(  # pylint: disable=protected-access
            bucket_field="cos_bucket_user_data_name", log_key_field="user_log_key", label="user"
        )

    assert result == "log line 1\nlog line 2"


def test_get_logs_from_cos_raises_runner_error_on_api_exception():
    """_get_logs_from_cos() raises RunnerError on ApiException."""
    from core.services.runners.abstract_runner import RunnerError  # pylint: disable=import-outside-toplevel

    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    runner._project.cos_bucket_user_data_name = "user-bucket"  # pylint: disable=protected-access
    mock_handler.cos.logs.side_effect = ApiException(status=403, reason="Forbidden")

    with patch.object(runner, "_is_cos_configured", return_value=True), patch.object(
        runner, "_get_fleet_name", return_value="fleet-name"
    ), patch.object(
        runner,
        "_build_cos_paths",
        return_value={
            "user_log_key": "users/1/jobs/j/logs.log",
            "provider_log_key": "providers/p/jobs/j/logs.log",
        },
    ):
        with pytest.raises(RunnerError):
            runner._get_logs_from_cos(  # pylint: disable=protected-access
                bucket_field="cos_bucket_user_data_name", log_key_field="user_log_key", label="user"
            )


# _is_cos_configured


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


# _get_api_key


def test_get_api_key_returns_from_settings():
    """_get_api_key() returns IBM_CLOUD_API_KEY from settings."""
    runner, _ = _make_runner()

    with patch(f"{_RUNNER_MOD}.settings") as mock_settings:
        mock_settings.IBM_CLOUD_API_KEY = "my-api-key"
        result = runner._get_api_key()  # pylint: disable=protected-access

    assert result == "my-api-key"


def test_get_api_key_raises_when_not_configured():
    """_get_api_key() raises RunnerError when no API key is configured."""
    from core.services.runners.abstract_runner import RunnerError  # pylint: disable=import-outside-toplevel

    runner, _ = _make_runner()

    with patch(f"{_RUNNER_MOD}.settings") as mock_settings, patch.dict("os.environ", {}, clear=True):
        mock_settings.IBM_CLOUD_API_KEY = None
        with pytest.raises(RunnerError, match="IBM_CLOUD_API_KEY"):
            runner._get_api_key()  # pylint: disable=protected-access


# _get_image


def test_get_image_returns_program_image():
    """_get_image() returns program.image when set."""
    runner, _ = _make_runner()
    runner.job.program.image = "my-image:latest"

    assert runner._get_image() == "my-image:latest"  # pylint: disable=protected-access


def test_get_image_falls_back_to_settings():
    """_get_image() falls back to FLEETS_DEFAULT_IMAGE when program has no image."""
    runner, _ = _make_runner()
    runner.job.program.image = None

    with patch(f"{_RUNNER_MOD}.settings") as mock_settings:
        mock_settings.FLEETS_DEFAULT_IMAGE = "default-image:latest"
        result = runner._get_image()  # pylint: disable=protected-access

    assert result == "default-image:latest"


def test_get_image_raises_when_no_image_and_no_default():
    """_get_image() raises RunnerError when no image and no default are configured."""
    from core.services.runners.abstract_runner import RunnerError  # pylint: disable=import-outside-toplevel

    runner, _ = _make_runner()
    runner.job.program.image = None

    with patch(f"{_RUNNER_MOD}.settings") as mock_settings:
        mock_settings.FLEETS_DEFAULT_IMAGE = None
        with pytest.raises(RunnerError):
            runner._get_image()  # pylint: disable=protected-access


# _get_max_instances


def test_get_max_instances_from_job_config():
    """_get_max_instances() uses job.config.workers when set."""
    runner, _ = _make_runner()
    runner.job.config.workers = 3

    assert runner._get_max_instances() == 3  # pylint: disable=protected-access


def test_get_max_instances_falls_back_to_settings():
    """_get_max_instances() falls back to settings default when config has no workers."""
    runner, _ = _make_runner()
    runner.job.config = None

    with patch(f"{_RUNNER_MOD}.settings") as mock_settings:
        mock_settings.FLEETS_DEFAULT_MAX_INSTANCES = 5
        result = runner._get_max_instances()  # pylint: disable=protected-access

    assert result == 5


# _get_gpu_config


def test_get_gpu_config_returns_empty_when_no_gpu():
    """_get_gpu_config() returns empty dict when no compute_profile and job.gpu is False."""
    runner, _ = _make_runner()
    runner.job.compute_profile = None
    runner.job.gpu = False

    assert runner._get_gpu_config() == {}  # pylint: disable=protected-access


def test_get_gpu_config_returns_v100_for_legacy_gpu_flag():
    """_get_gpu_config() returns V100 config when job.gpu=True and no compute_profile."""
    runner, _ = _make_runner()
    runner.job.compute_profile = None
    runner.job.gpu = True

    config = runner._get_gpu_config()  # pylint: disable=protected-access

    assert config["scale_gpu"]["preferences"][0]["family"] == "v100"


def test_get_gpu_config_from_compute_profile():
    """_get_gpu_config() parses GPU config from compute_profile."""
    runner, _ = _make_runner()
    runner.job.compute_profile = "gx3d-24x120x1a100p"

    config = runner._get_gpu_config()  # pylint: disable=protected-access

    assert config["scale_gpu"]["preferences"][0]["family"] == "a100"


# _get_fleet_name


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


# _upload_arguments_to_cos


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
