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
    env = build_run_env_variables(primary_mount_path="/output")
    cmds = build_run_commands(app_run_commands=["python", "main.py"])
"""

from __future__ import annotations

import shlex


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
    primary_mount_path: str,
    primary_log_filename: str = "logs.log",
    secondary_mount_path: str | None = None,
    secondary_log_filename: str = "logs.log",
    secondary_log_filter_key: str | None = None,
) -> list[dict[str, str]]:
    """
    Build environment variables used by the logging wrapper command.

    The mount path already points to the desired COS prefix, so no log subdir
    is needed here.

    Args:
        primary_mount_path: Container path for the primary log store.
        primary_log_filename: File name for the primary log.
        secondary_mount_path: Container path for the secondary log store.
        secondary_log_filename: File name for the secondary log.
        secondary_log_filter_key: Text filter used to route lines to the
            secondary log.

    Returns:
        Environment variable definitions for ``run_env_variables``.

    Raises:
        ValueError: If the primary log configuration is incomplete, or if
            secondary log filtering is requested without a complete secondary
            log configuration.
    """
    if not primary_mount_path:
        raise ValueError("primary_mount_path is required.")

    run_env_variables = [
        {
            "type": "literal",
            "name": "PRIMARY_LOG_DIR",
            "value": primary_mount_path,
        },
        {
            "type": "literal",
            "name": "PRIMARY_LOG_PATH",
            "value": f"{primary_mount_path}/{primary_log_filename}",
        },
    ]

    if secondary_log_filter_key is not None:
        if not secondary_mount_path:
            raise ValueError("secondary_mount_path is required when secondary_log_filter_key is provided.")

        run_env_variables.extend(
            [
                {
                    "type": "literal",
                    "name": "SECONDARY_LOG_DIR",
                    "value": secondary_mount_path,
                },
                {
                    "type": "literal",
                    "name": "SECONDARY_LOG_PATH",
                    "value": f"{secondary_mount_path}/{secondary_log_filename}",
                },
                {
                    "type": "literal",
                    "name": "SECONDARY_LOG_FILTER_KEY",
                    "value": secondary_log_filter_key,
                },
            ]
        )

    return run_env_variables


def build_run_commands(
    *,
    app_run_commands: list[str],
    app_run_arguments: list[str] | None = None,
    secondary_log_filter_key: str | None = None,
) -> list[str]:
    """
    Build wrapper commands for fleet execution and logging.

    Args:
        app_run_commands: Command override for the application.
        app_run_arguments: Argument override for the application.
        secondary_log_filter_key: Text filter used to route lines to the
            secondary log. If not provided, only the primary log is written.

    Returns:
        Command definition for ``run_commands``.

    Raises:
        ValueError: If ``app_run_commands`` is empty.
    """
    if not app_run_commands:
        raise ValueError("app_run_commands is required.")

    app_parts = [*app_run_commands, *(app_run_arguments or [])]
    app_cmd = " ".join(shlex.quote(part) for part in app_parts)

    if secondary_log_filter_key is not None:
        script = (
            "set -eu; "
            'PIPE="/tmp/app.pipe"; '
            'STATUS_FILE="/tmp/app.status"; '
            'rm -f "$PIPE" "$STATUS_FILE"; '
            'mkfifo "$PIPE"; '
            'mkdir -p "$PRIMARY_LOG_DIR" "$SECONDARY_LOG_DIR"; '
            'tee -a "$PRIMARY_LOG_PATH" < "$PIPE" | '
            'awk -v pat="$SECONDARY_LOG_FILTER_KEY" '
            '-v out="$SECONDARY_LOG_PATH" '
            "'index($0, pat) { print >> out; fflush(out) }' & "
            "LOGGER_PID=$!; "
            f'( {app_cmd}; printf "%s\\n" "$?" > "$STATUS_FILE" ) > "$PIPE" 2>&1; '
            'wait "$LOGGER_PID" || true; '
            'if [ ! -f "$STATUS_FILE" ]; then '
            '  echo "logging wrapper error: status file was not created" >&2; '
            '  rm -f "$PIPE" "$STATUS_FILE"; '
            "  exit 1; "
            "fi; "
            'STATUS="$(cat "$STATUS_FILE")"; '
            'rm -f "$PIPE" "$STATUS_FILE"; '
            'case "$STATUS" in '
            '  ""|*[!0-9]*) '
            '    echo "logging wrapper error: invalid status: $STATUS" >&2; '
            "    exit 1 "
            "    ;; "
            "esac; "
            'exit "$STATUS"'
        )
    else:
        script = f'set -eu; mkdir -p "$PRIMARY_LOG_DIR"; exec {app_cmd} >> "$PRIMARY_LOG_PATH" 2>&1'

    return ["sh", "-c", script]
