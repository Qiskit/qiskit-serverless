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
Pure helper functions for building fleet run configurations.

These functions produce the ``run_volume_mounts``, ``run_env_variables``,
and ``run_commands`` payloads consumed by :meth:`FleetHandler.submit_job`
via its ``extra_fields`` parameter.

Example::

    from core.ibm_cloud.code_engine.fleets.utils import (
        build_run_volume_mounts,
        build_run_env_variables,
        build_run_commands,
    )

    mounts = build_run_volume_mounts(
        mounts=[("/output", "my-pds", "user/job-1")]
    )
    env = build_run_env_variables(paths, decrypted_env_vars)
    cmds = build_run_commands(app_run_commands=["python", "main.py"])
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.conf import settings

from core.models import CodeEngineProject, Job

FUNCTION_USER_DATA_PATH = "/function_user_data"  # user bucket  — function-scoped data (entrypoint, wrapper, user files)
JOB_USER_DATA_PATH = "/job_user_data"  # user bucket  — job-scoped data (arguments, logs, results)
FUNCTION_PROVIDER_DATA_PATH = "/function_provider_data"  # provider bucket — function-scoped data (provider only)
JOB_PROVIDER_DATA_PATH = "/job_provider_data"  # provider bucket — job-scoped data (provider logs; provider only)


@dataclass(frozen=True)
class FleetJobPaths:  # pylint: disable=too-many-instance-attributes
    """Computed paths for a fleet job.

    ``cos_*`` fields are bucket-relative paths used by the Gateway to read/write COS objects.

    Fields ending in ``_prefix`` are directory-scoped (no trailing slash, no filename) and serve two purposes:
       - As the ``sub_path`` argument of a PDS volume mount
       - As the base for building COS keys for files whose names are only known at runtime

    Fields ending in ``_key`` are complete object keys, usable directly with the S3 client.

    ``container_*`` fields are absolute paths inside the running container.

    Mount layout (4 PDS volumes):
      FUNCTION_USER_DATA_PATH   → user bucket   @ cos_user_function_prefix   (function-scoped user data)
      JOB_USER_DATA_PATH        → user bucket   @ cos_user_job_prefix        (job-scoped user data)
      FUNCTION_PROVIDER_DATA_PATH → provider bucket @ cos_provider_function_prefix  (provider only)
      JOB_PROVIDER_DATA_PATH    → provider bucket @ cos_provider_job_prefix   (provider only)
    """

    # COS prefixes — used as PDS volume mount sub_paths and as key bases
    cos_user_function_prefix: str  # users/.../data/          — FUNCTION_USER_DATA_PATH sub_path
    cos_user_job_prefix: str  # users/.../jobs/{id}/     — JOB_USER_DATA_PATH sub_path
    cos_provider_function_prefix: Optional[
        str
    ]  # providers/.../data/  — FUNCTION_PROVIDER_DATA_PATH sub_path (None for custom)
    cos_provider_job_prefix: Optional[
        str
    ]  # providers/.../jobs/{id}/ — JOB_PROVIDER_DATA_PATH sub_path (None for custom)

    # COS complete object keys
    cos_user_log_key: str  # public log in the user bucket
    cos_results_key: str  # results.json in the user bucket
    cos_provider_log_key: Optional[str]  # private log in the provider bucket — None for custom jobs
    cos_function_entrypoint: str  # entrypoint script key in its respective function bucket
    cos_docker_entrypoint: str  # wrapper script key alongside the entrypoint

    # Container paths
    container_function_entrypoint: str  # absolute path to the function entrypoint inside the container
    container_docker_entrypoint: str  # absolute path to the wrapper script inside the container
    container_public_log_path: str  # written by wrapper, served by /logs
    container_private_log_path: Optional[str]  # written by wrapper, served by /provider-logs (None for custom)
    container_arguments_path: str  # read by the function at startup (injected as ARGUMENTS_PATH)
    container_result_path: str  # written by the function on completion (read back via cos_results_key)


def build_run_volume_mounts_for_job(paths: FleetJobPaths, project: CodeEngineProject) -> list[dict[str, str]]:
    """Build the complete volume mounts list for a fleet job.

    Custom jobs get 2 mounts (user bucket only).
    Provider jobs get 4 mounts (user + provider buckets).

    Args:
        paths: Pre-computed paths for the job (from :func:`build_job_paths`).
        project: CodeEngineProject with PDS names.

    Returns:
        Volume mount definitions ready for ``run_volume_mounts``.
    """
    mounts = [
        (FUNCTION_USER_DATA_PATH, project.pds_name_users, paths.cos_user_function_prefix),
        (JOB_USER_DATA_PATH, project.pds_name_users, paths.cos_user_job_prefix),
    ]
    if paths.cos_provider_function_prefix:
        mounts.append((FUNCTION_PROVIDER_DATA_PATH, project.pds_name_providers, paths.cos_provider_function_prefix))
        mounts.append((JOB_PROVIDER_DATA_PATH, project.pds_name_providers, paths.cos_provider_job_prefix))
    return build_run_volume_mounts(mounts=mounts)


def build_run_volume_mounts(
    *,
    mounts: list[tuple[str, str, str | None]],
) -> list[dict[str, str]]:
    """
    Build persistent data store volume mounts for a fleet.

    Args:
        mounts:
            List of ``(mount_path, reference, sub_path)`` tuples.

            - ``mount_path``: Container mount path.
            - ``reference``: Persistent data store name.
            - ``sub_path``: Optional COS prefix mounted at ``mount_path``.

    Returns:
        Volume mount definitions for ``run_volume_mounts``.

    Raises:
        ValueError: If ``mounts`` is empty or any required value is missing.
    """
    if not mounts:
        raise ValueError("mounts is required.")

    run_volume_mounts: list[dict[str, str]] = []

    for mount_path, reference, sub_path in mounts:
        if not mount_path:
            raise ValueError("mount_path is required.")
        if not reference:
            raise ValueError("reference is required.")

        mount = {
            "mount_path": mount_path,
            "reference": reference,
            "type": "persistent_data_store",
        }
        if sub_path:
            mount["sub_path"] = sub_path

        run_volume_mounts.append(mount)

    return run_volume_mounts


def build_run_env_variables(
    paths: FleetJobPaths,
    stored_env_vars: dict[str, str | None],
) -> list[dict[str, str]]:
    """Build the complete environment variable list for the Fleets container.

    Starts with decrypted stored job env vars as the base, then overlays
    system vars derived from paths. System vars always win on collision since
    they define the container's filesystem layout. New vars added at job
    creation time flow through automatically.

    Args:
        paths: Pre-computed paths for the job (from :func:`build_job_paths`).
        stored_env_vars: Decrypted env vars dict from ``job.env_vars``.

    Returns:
        List of env var dicts in Code Engine format
        ``[{"type": "literal", "name": "...", "value": "..."}]``.
        Empty values are excluded.
    """
    env = dict(stored_env_vars)

    # The full JSON job arguments are delivered to the container via COS at
    # ARGUMENTS_PATH (mounted file), so the duplicate ENV_JOB_ARGUMENTS literal
    # env var only widens plaintext exposure of (potentially sensitive) user
    # arguments in the Code Engine control plane. Drop it for fleets.
    env.pop("ENV_JOB_ARGUMENTS", None)

    gateway_host = getattr(settings, "FLEETS_GATEWAY_HOST", None)
    if gateway_host:
        env["ENV_JOB_GATEWAY_HOST"] = gateway_host

    flush_interval = getattr(settings, "FLEETS_LOG_FLUSH_INTERVAL_SECONDS", 15)
    env.update(
        {
            "PUBLIC_LOG_PATH": paths.container_public_log_path,
            "ARGUMENTS_PATH": paths.container_arguments_path,
            "RESULTS_PATH": paths.container_result_path,
            "LOG_FLUSH_INTERVAL_SECONDS": str(flush_interval),
            "LOG_SIZE_LIMIT_BYTES": str(getattr(settings, "FUNCTIONS_LOGS_SIZE_LIMIT", 52428800)),
        }
    )
    if paths.container_private_log_path is not None:
        env["PRIVATE_LOG_PATH"] = paths.container_private_log_path

    return [{"type": "literal", "name": k, "value": v} for k, v in env.items() if v]


def build_custom_job_paths(job: Job) -> FleetJobPaths:
    """COS paths for a custom (non-provider) job.

    The entrypoint and wrapper live in the user bucket at function scope
    (``FUNCTION_USER_DATA_PATH``). Arguments, logs, and results live in the
    user bucket at job scope (``JOB_USER_DATA_PATH``). There are no private logs
    and no provider bucket mounts.

    Field naming conventions:
      - ``cos_*``       — bucket-relative COS object keys or key prefixes,
                         used by the gateway to read/write objects via the S3 client.
      - ``container_*`` — absolute paths inside the running container,
                         injected as env vars (ARGUMENTS_PATH, RESULTS_PATH, etc.)
                         or passed directly to the wrapper/entrypoint command.
      - ``*_prefix``    — directory-scoped key (no trailing slash); doubles as the
                         ``sub_path`` for the PDS volume mount and as the base for
                         building object keys at runtime.
      - ``*_key``       — complete object key, usable directly with the S3 client.
      - ``*_entrypoint``— key or path to the script that CE runs as the job entry.
      - ``*_docker_entrypoint`` — key or path to the fleet wrapper script that
                                  handles log capture and invokes the entrypoint.

    Args:
        job: Job instance with no provider.
    """
    username = job.author.username
    program_title = job.program.title
    job_id = str(job.id)
    cos_user_function_data = f"users/{username}/custom_functions/{program_title}/data"
    cos_user_job_prefix = f"users/{username}/custom_functions/{program_title}/jobs/{job_id}"
    return FleetJobPaths(
        cos_user_function_prefix=cos_user_function_data,
        cos_user_job_prefix=cos_user_job_prefix,
        cos_provider_function_prefix=None,
        cos_provider_job_prefix=None,
        cos_user_log_key=f"{cos_user_job_prefix}/logs.log",
        cos_results_key=f"{cos_user_job_prefix}/results.json",
        cos_provider_log_key=None,
        cos_function_entrypoint=f"{cos_user_function_data}/{job.program.entrypoint}",
        cos_docker_entrypoint=f"{cos_user_function_data}/fleet_custom_job_wrapper.py",
        container_function_entrypoint=f"{FUNCTION_USER_DATA_PATH}/{job.program.entrypoint}",
        container_docker_entrypoint=f"{FUNCTION_USER_DATA_PATH}/fleet_custom_job_wrapper.py",
        container_private_log_path=None,
        container_public_log_path=f"{JOB_USER_DATA_PATH}/logs.log",
        container_arguments_path=f"{JOB_USER_DATA_PATH}/arguments.json",
        container_result_path=f"{JOB_USER_DATA_PATH}/results.json",
    )


def build_provider_job_paths(job: Job) -> FleetJobPaths:
    """COS paths for a provider job.

    The entrypoint and wrapper live in the provider bucket at function scope
    (``FUNCTION_PROVIDER_DATA_PATH``). User-facing data lives in the user bucket
    at both function scope (``FUNCTION_USER_DATA_PATH``) and job scope
    (``JOB_USER_DATA_PATH``). Private provider logs live in the provider bucket
    at job scope (``JOB_PROVIDER_DATA_PATH``).

    See :func:`build_custom_job_paths` for field naming conventions.

    Args:
        job: Job instance with a provider assigned.
    """
    username = job.author.username
    provider_name = job.program.provider.name
    program_title = job.program.title
    job_id = str(job.id)
    cos_user_function_data = f"users/{username}/provider_functions/{provider_name}/{program_title}/data"
    cos_user_job_prefix = f"users/{username}/provider_functions/{provider_name}/{program_title}/jobs/{job_id}"
    cos_provider_function_data = f"providers/{provider_name}/{program_title}/data"
    cos_provider_job_prefix = f"providers/{provider_name}/{program_title}/jobs/{job_id}"
    return FleetJobPaths(
        cos_user_function_prefix=cos_user_function_data,
        cos_user_job_prefix=cos_user_job_prefix,
        cos_provider_function_prefix=cos_provider_function_data,
        cos_provider_job_prefix=cos_provider_job_prefix,
        cos_user_log_key=f"{cos_user_job_prefix}/logs.log",
        cos_results_key=f"{cos_user_job_prefix}/results.json",
        cos_provider_log_key=f"{cos_provider_job_prefix}/logs.log",
        cos_function_entrypoint=f"{cos_provider_function_data}/{job.program.entrypoint}",
        cos_docker_entrypoint=f"{cos_provider_function_data}/fleet_provider_job_wrapper.py",
        container_function_entrypoint=f"{FUNCTION_PROVIDER_DATA_PATH}/{job.program.entrypoint}",
        container_docker_entrypoint=f"{FUNCTION_PROVIDER_DATA_PATH}/fleet_provider_job_wrapper.py",
        container_private_log_path=f"{JOB_PROVIDER_DATA_PATH}/logs.log",
        container_public_log_path=f"{JOB_USER_DATA_PATH}/logs.log",
        container_arguments_path=f"{JOB_USER_DATA_PATH}/arguments.json",
        container_result_path=f"{JOB_USER_DATA_PATH}/results.json",
    )


def build_job_paths(job: Job) -> FleetJobPaths:
    """Dispatcher: returns custom or provider COS paths depending on job type."""
    if job.program.provider:
        return build_provider_job_paths(job)
    return build_custom_job_paths(job)
