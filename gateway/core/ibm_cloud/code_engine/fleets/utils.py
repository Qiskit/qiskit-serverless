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
    env = build_run_env_variables(paths=paths)
    cmds = build_run_commands(app_run_commands=["python", "main.py"])
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Optional

from django.template.loader import get_template

from core.models import CodeEngineProject, Job

USER_MOUNT_PATH = "/data"
FUNCTION_MOUNT_PATH = "/function_data"


@dataclass(frozen=True)
class FleetJobPaths:  # pylint: disable=too-many-instance-attributes
    """Computed paths for a fleet job.

    ``cos_*`` fields are bucket-relative paths used by the gateway when
    reading or writing objects in COS.  Fields ending in ``_prefix`` are
    directory-scoped (no trailing slash, no filename) and serve two purposes:
    as the ``sub_path`` argument of a PDS volume mount, and as the base for
    building COS keys for files whose names are only known at runtime (e.g.
    artifact members from a tarball).  Fields ending in ``_key`` are complete
    COS object keys ready to be passed directly to the COS client.

    ``container_*`` fields are absolute filesystem paths inside the running
    container, exported to the wrapper script as environment variables.
    ``None`` on any optional field means the concept does not apply to this
    job type (e.g. no private log for custom jobs).
    """

    # COS side prefixes (volume-mount sub_path + artifact key base)

    # sub_path for /data mount; base for non-entrypoint artifact keys ({prefix}/{member})
    cos_user_job_prefix: str
    # sub_path for /function_data mount (custom jobs); base for entrypoint artifact key
    cos_user_function_prefix: str
    # sub_path for /function_data mount (provider jobs); base for entrypoint artifact key — None for custom jobs
    cos_provider_function_prefix: Optional[str]

    # COS side: complete object keys (passed directly to the COS client to read or write with the S3 client)
    cos_user_log_key: str  # public log in the user bucket
    cos_results_key: str  # results.json in the user bucket
    cos_provider_log_key: Optional[str]  # private log in the provider bucket — None for custom jobs

    # Container side, used by the function
    container_entrypoint: str  # absolute path to the function script inside the container
    container_public_log_path: str  # written by wrapper, served by /logs
    container_private_log_path: Optional[str]  # written by wrapper, served by /provider-logs
    container_arguments_path: str  # read by the function at startup (injected as ARGUMENTS_PATH)
    container_result_path: str  # written by the function on completion (read back via cos_results_key)


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
    *,
    paths: FleetJobPaths,
    flush_interval_seconds: int = 15,
    extra: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """
    Build environment variables used by the logging wrapper command.

    Args:
        paths: Pre-computed paths for the job (from :func:`build_cos_paths`).
        flush_interval_seconds: Period (in seconds) between log uploads from
            the local working directory to the COS-backed mount.
        extra: Additional environment variable definitions appended after the
            ones built by this function.

    Returns:
        Environment variable definitions for ``run_env_variables``.
    """
    system_vars = [
        {
            "type": "literal",
            "name": "PUBLIC_LOG_PATH",
            "value": paths.container_public_log_path,
        },
        {
            "type": "literal",
            "name": "ARGUMENTS_PATH",
            "value": paths.container_arguments_path,
        },
        {
            "type": "literal",
            "name": "RESULTS_PATH",
            "value": paths.container_result_path,
        },
        {
            "type": "literal",
            "name": "LOG_FLUSH_INTERVAL_SECONDS",
            "value": str(flush_interval_seconds),
        },
    ]

    if paths.container_private_log_path is not None:
        system_vars.append(
            {
                "type": "literal",
                "name": "PRIVATE_LOG_PATH",
                "value": paths.container_private_log_path,
            }
        )

    merged = {e["name"]: e for e in (extra or [])}
    merged.update({e["name"]: e for e in system_vars})
    return list(merged.values())


def build_run_commands(
    *,
    app_run_commands: list[str],
    app_run_arguments: list[str] | None = None,
    is_provider_function: bool = False,
) -> list[str]:
    """
    Build wrapper commands for fleet execution and logging.

    Args:
        app_run_commands: Command override for the application.
        app_run_arguments: Argument override for the application.
        is_provider_function: When True, the wrapper splits the application
            output into a public log and a private log (provider job). When
            False, the wrapper writes a single prefix-stripped public log
            (custom/user job).

    Returns:
        Command definition for ``run_commands``.

    Raises:
        ValueError: If ``app_run_commands`` is empty.
    """
    if not app_run_commands:
        raise ValueError("app_run_commands is required.")

    app_parts = [*app_run_commands, *(app_run_arguments or [])]
    app_cmd = " ".join(shlex.quote(part) for part in app_parts)

    template_name = "fleet_provider_job_wrapper.tmpl" if is_provider_function else "fleet_custom_job_wrapper.tmpl"
    script = get_template(template_name).render({"app_cmd": app_cmd})

    return ["sh", "-c", script]


def build_custom_job_cos_paths(job: Job) -> FleetJobPaths:
    """COS paths for a custom (non-provider) job.

    The entrypoint lives in the user bucket at function scope and runs from
    ``/function_data``. User data and public logs live in the user bucket at
    job scope. There are no private logs.

    Args:
        job: Job instance with no provider.
    """
    username = job.author.username
    program_title = job.program.title
    job_id = str(job.id)
    cos_user_function_prefix = f"users/{username}/custom_functions/{program_title}"
    cos_user_job_prefix = f"{cos_user_function_prefix}/jobs/{job_id}"
    return FleetJobPaths(
        # COS paths
        cos_user_function_prefix=cos_user_function_prefix,
        cos_user_job_prefix=cos_user_job_prefix,
        cos_user_log_key=f"{cos_user_job_prefix}/logs.log",
        cos_results_key=f"{cos_user_job_prefix}/results.json",
        cos_provider_function_prefix=None,
        cos_provider_log_key=None,
        # Mounting paths inside the function
        container_entrypoint=f"{FUNCTION_MOUNT_PATH}/{job.program.entrypoint}",
        container_private_log_path=None,
        container_public_log_path=f"{USER_MOUNT_PATH}/logs.log",
        container_arguments_path=f"{USER_MOUNT_PATH}/arguments.json",
        container_result_path=f"{USER_MOUNT_PATH}/results.json",
    )


def build_provider_job_cos_paths(job: Job) -> FleetJobPaths:
    """COS paths for a provider job.

    Both user bucket (public logs + data) and provider bucket (entrypoint at
    function scope, private logs at job scope) are used.

    Args:
        job: Job instance with a provider assigned.
    """
    username = job.author.username
    provider_name = job.program.provider.name
    program_title = job.program.title
    job_id = str(job.id)
    cos_user_function_prefix = f"users/{username}/provider_functions/{provider_name}/{program_title}"
    cos_provider_function_prefix = f"providers/{provider_name}/{program_title}"
    cos_user_job_prefix = f"{cos_user_function_prefix}/jobs/{job_id}"
    cos_provider_job_prefix = f"{cos_provider_function_prefix}/jobs/{job_id}"
    return FleetJobPaths(
        # COS paths
        cos_user_function_prefix=cos_user_function_prefix,
        cos_user_job_prefix=cos_user_job_prefix,
        cos_user_log_key=f"{cos_user_job_prefix}/logs.log",
        cos_results_key=f"{cos_user_job_prefix}/results.json",
        cos_provider_function_prefix=cos_provider_function_prefix,
        cos_provider_log_key=f"{cos_provider_job_prefix}/logs.log",
        # Mounting paths inside the function
        container_entrypoint=f"{FUNCTION_MOUNT_PATH}/{job.program.entrypoint}",
        container_private_log_path=f"{FUNCTION_MOUNT_PATH}/jobs/{job_id}/logs.log",
        container_public_log_path=f"{USER_MOUNT_PATH}/logs.log",
        container_arguments_path=f"{USER_MOUNT_PATH}/arguments.json",
        container_result_path=f"{USER_MOUNT_PATH}/results.json",
    )


def build_cos_paths(job: Job) -> FleetJobPaths:
    """Dispatcher: returns custom or provider COS paths depending on job type."""
    if job.program.provider:
        return build_provider_job_cos_paths(job)
    return build_custom_job_cos_paths(job)


def build_run_volume_mounts_for_job(paths: FleetJobPaths, project: CodeEngineProject) -> list[dict[str, str]]:
    """Build the complete volume mounts list for a fleet job.

    Args:
        paths: Pre-computed paths for the job (from :func:`build_cos_paths`).
        project: CodeEngineProject with PDS names.

    Returns:
        Volume mount definitions ready for ``run_volume_mounts``.
    """
    mounts = [(USER_MOUNT_PATH, project.pds_name_users, paths.cos_user_job_prefix)]
    if paths.cos_provider_function_prefix:
        mounts.append((FUNCTION_MOUNT_PATH, project.pds_name_providers, paths.cos_provider_function_prefix))
    else:
        mounts.append((FUNCTION_MOUNT_PATH, project.pds_name_users, paths.cos_user_function_prefix))
    return build_run_volume_mounts(mounts=mounts)
