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

"""Unit tests for core/ibm_cloud/code_engine/fleets/utils.py."""

import base64
from unittest.mock import MagicMock, patch

import pytest

from core.ibm_cloud.code_engine.fleets.utils import (
    FleetJobPaths,
    build_job_paths,
    build_run_commands,
    build_run_env_variables,
    build_run_volume_mounts,
    build_run_volume_mounts_for_job,
    FUNCTION_USER_DATA_PATH,
    JOB_USER_DATA_PATH,
    FUNCTION_PROVIDER_DATA_PATH,
    JOB_PROVIDER_DATA_PATH,
)


def _make_job(*, username="alice", title="my-func", entrypoint="main.py", job_id="job-001", provider=None):
    """Return a minimal mock Job for path-builder tests."""
    job = MagicMock()
    job.author.username = username
    job.program.title = title
    job.program.entrypoint = entrypoint
    job.program.provider = provider
    job.id = job_id
    return job


def _make_paths(public_log_path="/output/logs.log", private_log_path=None, arguments_path="/output/arguments.json"):
    """Return a minimal FleetJobPaths for env-variable tests."""
    return FleetJobPaths(
        cos_user_job_prefix="u/job-1",
        cos_user_function_prefix="u/fn",
        cos_provider_function_prefix=None,
        cos_provider_job_prefix=None,
        cos_user_log_key="u/job-1/logs.log",
        cos_results_key="u/job-1/results.json",
        cos_provider_log_key=None,
        cos_function_entrypoint="u/fn/main.py",
        cos_docker_entrypoint="u/fn/fleet_custom_job_wrapper.py",
        container_function_entrypoint="/function_user_data/main.py",
        container_docker_entrypoint="/function_user_data/fleet_custom_job_wrapper.py",
        container_public_log_path=public_log_path,
        container_private_log_path=private_log_path,
        container_arguments_path=arguments_path,
        container_result_path="/output/results.json",
    )


def test_build_job_paths_custom_function():
    """COS paths for a custom function follow users/.../data/ and jobs/{id}/ layout."""
    job = _make_job(username="IBMid-50FJDA", title="hello-world", entrypoint="main.py", job_id="8be4df61-93ca")

    paths = build_job_paths(job)

    # COS structure: users/{user}/custom_functions/{title}/data/ + jobs/{id}/
    assert paths.cos_user_function_prefix == "users/IBMid-50FJDA/custom_functions/hello-world/data"
    assert paths.cos_user_job_prefix == "users/IBMid-50FJDA/custom_functions/hello-world/jobs/8be4df61-93ca"

    # Complete COS keys
    assert paths.cos_user_log_key == "users/IBMid-50FJDA/custom_functions/hello-world/jobs/8be4df61-93ca/logs.log"
    assert paths.cos_results_key == "users/IBMid-50FJDA/custom_functions/hello-world/jobs/8be4df61-93ca/results.json"
    assert paths.cos_function_entrypoint == "users/IBMid-50FJDA/custom_functions/hello-world/data/main.py"
    assert (
        paths.cos_docker_entrypoint
        == "users/IBMid-50FJDA/custom_functions/hello-world/data/fleet_custom_job_wrapper.py"
    )

    # No provider paths
    assert paths.cos_provider_function_prefix is None
    assert paths.cos_provider_job_prefix is None
    assert paths.cos_provider_log_key is None

    # Container paths use the 4-variable mount constants
    assert paths.container_function_entrypoint == f"{FUNCTION_USER_DATA_PATH}/main.py"
    assert paths.container_docker_entrypoint == f"{FUNCTION_USER_DATA_PATH}/fleet_custom_job_wrapper.py"
    assert paths.container_public_log_path == f"{JOB_USER_DATA_PATH}/logs.log"
    assert paths.container_private_log_path is None
    assert paths.container_arguments_path == f"{JOB_USER_DATA_PATH}/arguments.json"
    assert paths.container_result_path == f"{JOB_USER_DATA_PATH}/results.json"


def test_build_job_paths_provider_function():
    """COS paths for a provider function use both user and provider buckets with data/ and jobs/ subdirs."""
    provider = MagicMock()
    provider.name = "Q-CTRL"
    job = _make_job(
        username="IBMid-50FJDA",
        title="sampler-v2",
        entrypoint="main.py",
        job_id="8be4df61-93ca",
        provider=provider,
    )

    paths = build_job_paths(job)

    # User bucket COS structure
    assert paths.cos_user_function_prefix == "users/IBMid-50FJDA/provider_functions/Q-CTRL/sampler-v2/data"
    assert paths.cos_user_job_prefix == "users/IBMid-50FJDA/provider_functions/Q-CTRL/sampler-v2/jobs/8be4df61-93ca"

    # Provider bucket COS structure
    assert paths.cos_provider_function_prefix == "providers/Q-CTRL/sampler-v2/data"
    assert paths.cos_provider_job_prefix == "providers/Q-CTRL/sampler-v2/jobs/8be4df61-93ca"

    # Complete COS keys
    assert paths.cos_user_log_key == "users/IBMid-50FJDA/provider_functions/Q-CTRL/sampler-v2/jobs/8be4df61-93ca/logs.log"  # fmt: skip
    assert paths.cos_results_key == "users/IBMid-50FJDA/provider_functions/Q-CTRL/sampler-v2/jobs/8be4df61-93ca/results.json"  # fmt: skip
    assert paths.cos_provider_log_key == "providers/Q-CTRL/sampler-v2/jobs/8be4df61-93ca/logs.log"
    assert paths.cos_function_entrypoint == "providers/Q-CTRL/sampler-v2/data/main.py"
    assert paths.cos_docker_entrypoint == "providers/Q-CTRL/sampler-v2/data/fleet_provider_job_wrapper.py"

    # Container paths use the 4-variable mount constants
    assert paths.container_function_entrypoint == f"{FUNCTION_PROVIDER_DATA_PATH}/main.py"
    assert paths.container_docker_entrypoint == f"{FUNCTION_PROVIDER_DATA_PATH}/fleet_provider_job_wrapper.py"
    assert paths.container_public_log_path == f"{JOB_USER_DATA_PATH}/logs.log"
    assert paths.container_private_log_path == f"{JOB_PROVIDER_DATA_PATH}/logs.log"
    assert paths.container_arguments_path == f"{JOB_USER_DATA_PATH}/arguments.json"
    assert paths.container_result_path == f"{JOB_USER_DATA_PATH}/results.json"


def test_build_run_volume_mounts_happy_path():
    """build_run_volume_mounts returns correct definitions including optional sub_path."""
    result = build_run_volume_mounts(mounts=[("/output", "my-pds", "user/job-1"), ("/logs", "log-pds", None)])
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


def test_build_run_volume_mounts_custom_function():
    """Custom jobs get exactly 2 mounts — both on the user PDS."""
    job = _make_job(title="my-func", entrypoint="run.py", job_id="job-001")
    paths = build_job_paths(job)
    project = MagicMock()
    project.pds_name_users = "user-pds"
    project.pds_name_providers = "provider-pds"

    mounts = build_run_volume_mounts_for_job(paths, project)

    assert len(mounts) == 2
    by_path = {m["mount_path"]: m for m in mounts}

    assert by_path[FUNCTION_USER_DATA_PATH]["reference"] == "user-pds"
    assert by_path[FUNCTION_USER_DATA_PATH]["sub_path"] == "users/alice/custom_functions/my-func/data"
    assert by_path[JOB_USER_DATA_PATH]["reference"] == "user-pds"
    assert by_path[JOB_USER_DATA_PATH]["sub_path"] == "users/alice/custom_functions/my-func/jobs/job-001"
    assert FUNCTION_PROVIDER_DATA_PATH not in by_path
    assert JOB_PROVIDER_DATA_PATH not in by_path


def test_build_run_volume_mounts_provider_function():
    """Provider jobs get exactly 4 mounts — 2 user PDS + 2 provider PDS."""
    provider = MagicMock()
    provider.name = "acme"
    job = _make_job(title="sampler", entrypoint="main.py", job_id="job-002", provider=provider)
    paths = build_job_paths(job)
    project = MagicMock()
    project.pds_name_users = "user-pds"
    project.pds_name_providers = "provider-pds"

    mounts = build_run_volume_mounts_for_job(paths, project)

    assert len(mounts) == 4
    by_path = {m["mount_path"]: m for m in mounts}

    assert by_path[FUNCTION_USER_DATA_PATH]["reference"] == "user-pds"
    assert by_path[FUNCTION_USER_DATA_PATH]["sub_path"] == "users/alice/provider_functions/acme/sampler/data"
    assert by_path[JOB_USER_DATA_PATH]["reference"] == "user-pds"
    assert by_path[JOB_USER_DATA_PATH]["sub_path"] == "users/alice/provider_functions/acme/sampler/jobs/job-002"
    assert by_path[FUNCTION_PROVIDER_DATA_PATH]["reference"] == "provider-pds"
    assert by_path[FUNCTION_PROVIDER_DATA_PATH]["sub_path"] == "providers/acme/sampler/data"
    assert by_path[JOB_PROVIDER_DATA_PATH]["reference"] == "provider-pds"
    assert by_path[JOB_PROVIDER_DATA_PATH]["sub_path"] == "providers/acme/sampler/jobs/job-002"
    assert all(m["type"] == "persistent_data_store" for m in mounts)


def test_build_run_env_variables_passes_through_stored_vars():
    """build_run_env_variables passes stored env vars through to output."""
    stored = {"ENV_JOB_GATEWAY_TOKEN": "tok", "CUSTOM_VAR": "custom"}
    result = build_run_env_variables(_make_paths(), stored)
    by_name = {e["name"]: e["value"] for e in result}
    assert by_name["ENV_JOB_GATEWAY_TOKEN"] == "tok"
    assert by_name["CUSTOM_VAR"] == "custom"
    assert all(e["type"] == "literal" for e in result)


def test_build_run_env_variables_overlays_system_vars():
    """build_run_env_variables includes system vars derived from paths."""
    result = build_run_env_variables(_make_paths(), {})
    by_name = {e["name"]: e["value"] for e in result}
    assert by_name["PUBLIC_LOG_PATH"] == "/output/logs.log"
    assert by_name["ARGUMENTS_PATH"] == "/output/arguments.json"
    assert by_name["RESULTS_PATH"] == "/output/results.json"
    assert by_name["LOG_FLUSH_INTERVAL_SECONDS"] == "15"
    assert "PRIVATE_LOG_PATH" not in by_name


def test_build_run_env_variables_system_vars_override_stored():
    """build_run_env_variables system vars override stored vars with the same name."""
    stored = {"ARGUMENTS_PATH": "/old/stale/path", "RESULTS_PATH": "/old/results.json"}
    result = build_run_env_variables(_make_paths(arguments_path="/data/arguments.json"), stored)
    names = [e["name"] for e in result]
    assert len(names) == len(set(names)), f"Duplicate env var names: {names}"
    by_name = {e["name"]: e["value"] for e in result}
    assert by_name["ARGUMENTS_PATH"] == "/data/arguments.json"
    assert by_name["RESULTS_PATH"] == "/output/results.json"


def test_build_run_env_variables_no_duplicates():
    """build_run_env_variables produces no duplicate env var names."""
    stored = {"PUBLIC_LOG_PATH": "/old", "RESULTS_PATH": "/old/r.json", "MY_VAR": "v"}
    result = build_run_env_variables(_make_paths(), stored)
    names = [e["name"] for e in result]
    assert len(names) == len(set(names))


def test_build_run_env_variables_excludes_empty_values():
    """build_run_env_variables excludes entries with empty or falsy values."""
    stored = {"KEEP": "yes", "DROP": "", "ALSO_DROP": None}
    result = build_run_env_variables(_make_paths(), stored)
    by_name = {e["name"]: e["value"] for e in result}
    assert "KEEP" in by_name
    assert "DROP" not in by_name
    assert "ALSO_DROP" not in by_name


def test_build_run_env_variables_with_private_log():
    """build_run_env_variables includes PRIVATE_LOG_PATH when container_private_log_path is set."""
    result = build_run_env_variables(
        _make_paths(public_log_path="/public/logs.log", private_log_path="/private/logs.log"),
        {},
    )
    by_name = {e["name"]: e["value"] for e in result}
    assert by_name["PUBLIC_LOG_PATH"] == "/public/logs.log"
    assert by_name["PRIVATE_LOG_PATH"] == "/private/logs.log"


def test_build_run_env_variables_without_private_log():
    """build_run_env_variables omits PRIVATE_LOG_PATH when container_private_log_path is None."""
    result = build_run_env_variables(_make_paths(private_log_path=None), {})
    names = {e["name"] for e in result}
    assert "PRIVATE_LOG_PATH" not in names


def test_build_run_env_variables_gateway_host_override():
    """build_run_env_variables overrides ENV_JOB_GATEWAY_HOST from FLEETS_GATEWAY_HOST setting."""
    stored = {"ENV_JOB_GATEWAY_HOST": "https://original.example.com"}
    with patch("core.ibm_cloud.code_engine.fleets.utils.settings") as mock_settings:
        mock_settings.FLEETS_GATEWAY_HOST = "https://fleets.example.com"
        mock_settings.FLEETS_LOG_FLUSH_INTERVAL_SECONDS = 15
        result = build_run_env_variables(_make_paths(), stored)
    by_name = {e["name"]: e["value"] for e in result}
    assert by_name["ENV_JOB_GATEWAY_HOST"] == "https://fleets.example.com"


def test_build_run_env_variables_flush_interval_default():
    """build_run_env_variables defaults LOG_FLUSH_INTERVAL_SECONDS to 15."""
    result = build_run_env_variables(_make_paths(), {})
    by_name = {e["name"]: e["value"] for e in result}
    assert by_name["LOG_FLUSH_INTERVAL_SECONDS"] == "15"


def test_build_run_env_variables_flush_interval_from_settings():
    """build_run_env_variables reads LOG_FLUSH_INTERVAL_SECONDS from settings."""
    with patch("core.ibm_cloud.code_engine.fleets.utils.settings") as mock_settings:
        mock_settings.FLEETS_LOG_FLUSH_INTERVAL_SECONDS = 42
        mock_settings.FLEETS_GATEWAY_HOST = None
        result = build_run_env_variables(_make_paths(), {})
    by_name = {e["name"]: e["value"] for e in result}
    assert by_name["LOG_FLUSH_INTERVAL_SECONDS"] == "42"


def test_build_run_commands_returns_python_with_wrapper_path():
    """build_run_commands returns ['python', wrapper_path] to run the COS-mounted script directly."""
    result = build_run_commands(wrapper_path="/function_user_data/fleet_custom_job_wrapper.py")
    assert result == ["python", "/function_user_data/fleet_custom_job_wrapper.py"]


def test_build_run_commands_provider_wrapper_path():
    """build_run_commands with provider wrapper path returns correct command."""
    result = build_run_commands(wrapper_path="/function_provider_data/fleet_provider_job_wrapper.py")
    assert result == ["python", "/function_provider_data/fleet_provider_job_wrapper.py"]
