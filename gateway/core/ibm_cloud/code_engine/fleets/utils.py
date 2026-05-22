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
    env = build_run_env_variables(public_mount_path="/output")
    cmds = build_run_commands(app_run_commands=["python", "main.py"])
"""

from __future__ import annotations

import shlex

from django.template.loader import get_template


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
    public_mount_path: str,
    public_log_filename: str = "logs.log",
    private_mount_path: str | None = None,
    private_log_filename: str = "logs.log",
    flush_interval_seconds: int = 15,
) -> list[dict[str, str]]:
    """
    Build environment variables used by the logging wrapper command.

    The mount path already points to the desired COS prefix, so no log subdir
    is needed here.

    Args:
        public_mount_path: Container path for the public log store. Always
            present: it is the file served by ``/logs`` to the job's author
            (``filter_logs_with_public_tags`` for provider jobs, full output
            with prefixes stripped for custom jobs).
        public_log_filename: File name for the public log.
        private_mount_path: Container path for the private log store.
            Required only for provider jobs that emit a separate private
            stream served by ``/provider-logs``.
        private_log_filename: File name for the private log.
        flush_interval_seconds: Period (in seconds) between log uploads from
            the local working directory to the COS-backed mount.

    Returns:
        Environment variable definitions for ``run_env_variables``.

    Raises:
        ValueError: If the public log configuration is incomplete.
    """
    if not public_mount_path:
        raise ValueError("public_mount_path is required.")

    run_env_variables = [
        {
            "type": "literal",
            "name": "PUBLIC_LOG_DIR",
            "value": public_mount_path,
        },
        {
            "type": "literal",
            "name": "PUBLIC_LOG_PATH",
            "value": f"{public_mount_path}/{public_log_filename}",
        },
        {
            "type": "literal",
            "name": "LOG_FLUSH_INTERVAL_SECONDS",
            "value": str(flush_interval_seconds),
        },
    ]

    if private_mount_path is not None:
        run_env_variables.extend(
            [
                {
                    "type": "literal",
                    "name": "PRIVATE_LOG_DIR",
                    "value": private_mount_path,
                },
                {
                    "type": "literal",
                    "name": "PRIVATE_LOG_PATH",
                    "value": f"{private_mount_path}/{private_log_filename}",
                },
            ]
        )

    return run_env_variables


def build_run_commands(
    *,
    app_run_commands: list[str],
    app_run_arguments: list[str] | None = None,
    with_private_log: bool = False,
) -> list[str]:
    """
    Build wrapper commands for fleet execution and logging.

    Args:
        app_run_commands: Command override for the application.
        app_run_arguments: Argument override for the application.
        with_private_log: When True, the wrapper splits the application
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

    template_name = "fleet_provider_job_wrapper.tmpl" if with_private_log else "fleet_custom_job_wrapper.tmpl"
    script = get_template(template_name).render({"app_cmd": app_cmd})

    return ["sh", "-c", script]
