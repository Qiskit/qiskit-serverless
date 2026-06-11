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
Tests that run the fleet wrapper scripts inside a real Docker container.

These tests verify end-to-end wrapper behaviour:
  - custom-job wrapper:  all lines → public log, [PUBLIC]/[PRIVATE] prefixes stripped
  - provider-job wrapper: [PUBLIC] lines → public log; [PRIVATE] + plain → private log
  - exit-code propagation + log flush on failure
  - log size limiting: truncation header + tail-only output when limit exceeded
  - periodic flush: logs reach COS while the job is still running (not only on exit)

Each test disables the periodic uploader (LOG_FLUSH_INTERVAL_SECONDS=999) unless the
test itself is specifically exercising periodic flushing, so the EXIT trap is the only
flush path exercised by the filtering and truncation tests.

Skipped automatically when the Docker daemon is unavailable.
"""

import os
import subprocess
import tempfile
import time

import pytest

import json

from django.template.loader import get_template

_DOCKER_TMP = "./tests/resources/tmp"


# ---------------------------------------------------------------------------
# Helpers / marks
# ---------------------------------------------------------------------------

_DOCKER_IMAGE = "python:3-alpine"


def _render_wrapper(app_run_commands: list[str], *, is_provider_function: bool = False) -> list[str]:
    """Render the fleet wrapper template and return a ['python', '-c', script] command.

    In production the wrapper runs from the PDS-mounted file. In tests we pass the
    rendered script inline via python -c so no filesystem mount is needed.
    """
    template_name = "fleet_provider_job_wrapper.py" if is_provider_function else "fleet_custom_job_wrapper.py"
    script = get_template(template_name).render({"app_cmd": json.dumps(app_run_commands)})
    return ["python", "-c", script]


def _docker_available() -> bool:
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


docker_required = pytest.mark.skipif(not _docker_available(), reason="Docker daemon not available")

# Shell program used by most tests.  Emits all three line types with a sleep
# in the middle so we also exercise the final-flush path.
_APP_SCRIPT = "\n".join(
    [
        "printf '[PUBLIC] public line 1\\n'",
        "printf '[PRIVATE] private line 1\\n'",
        "printf 'plain line 1\\n'",
        "sleep 1",
        "printf '[PUBLIC] public line 2\\n'",
        "printf '[private] private line 2\\n'",  # lowercase — must also be filtered
        "printf 'plain line 2\\n'",
    ]
)


def _docker_run(
    run_commands: list[str], env_pairs: dict[str, str], volume: str, timeout: int = 90
) -> subprocess.CompletedProcess:
    """Run *run_commands* inside Docker with the given env vars and volume mount.

    volume: bind-mount spec for Docker's -v flag, e.g. "/host/cos:/cos".
    """
    env_flags: list[str] = []
    for name, value in env_pairs.items():
        env_flags += ["-e", f"{name}={value}"]

    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        volume,
        *env_flags,
        _DOCKER_IMAGE,
        *run_commands,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@docker_required
def test_custom_wrapper_all_lines_reach_public_log():
    """Custom wrapper writes all output to the public log with prefixes stripped.

    All three line categories ([PUBLIC], [PRIVATE], plain) reach the single public
    log with the periodic uploader disabled, so every line is captured by the EXIT
    trap on job completion. Case-insensitive prefix matching is verified via the
    lowercase [private] tag in _APP_SCRIPT. The truncation header must be absent
    because the output is well under any reasonable size limit.
    """
    run_commands = _render_wrapper(["sh", "-c", _APP_SCRIPT])

    with tempfile.TemporaryDirectory(dir=_DOCKER_TMP) as tmp:
        cos_dir = f"{tmp}/cos"
        os.makedirs(f"{cos_dir}/public")
        result = _docker_run(
            run_commands,
            {
                "PUBLIC_LOG_PATH": "/cos/public/logs.log",
                "LOG_FLUSH_INTERVAL_SECONDS": "999",
            },
            f"{cos_dir}:/cos",
        )
        assert result.returncode == 0, result.stderr

        with open(f"{cos_dir}/public/logs.log") as f:
            public = f.read()

    for line in ("public line 1", "public line 2", "private line 1", "private line 2", "plain line 1", "plain line 2"):
        assert line in public, f"expected '{line}' in public log:\n{public}"

    for tag in ("[PUBLIC]", "[public]", "[PRIVATE]", "[private]"):
        assert tag not in public, f"tag '{tag}' must be stripped from public log"

    assert "Logs exceeded maximum allowed size" not in public


@docker_required
def test_provider_wrapper_splits_public_and_private_logs():
    """Provider wrapper splits output into two logs with correct filtering.

    [PUBLIC] lines (both cases) go only to the public log with the prefix stripped.
    [PRIVATE] lines (both cases) and plain lines go only to the private log with the
    prefix stripped on [PRIVATE] and kept verbatim on plain lines. [PUBLIC] lines must
    not leak into the private log. Lines after the sleep in _APP_SCRIPT are captured by
    the EXIT trap (periodic uploader is disabled). The truncation header must be absent
    because the output is well under any reasonable size limit.
    """
    run_commands = _render_wrapper(["sh", "-c", _APP_SCRIPT], is_provider_function=True)

    with tempfile.TemporaryDirectory(dir=_DOCKER_TMP) as tmp:
        cos_dir = f"{tmp}/cos"
        os.makedirs(f"{cos_dir}/public")
        os.makedirs(f"{cos_dir}/provider")
        result = _docker_run(
            run_commands,
            {
                "PUBLIC_LOG_PATH": "/cos/public/logs.log",
                "PRIVATE_LOG_PATH": "/cos/provider/logs.log",
                "LOG_FLUSH_INTERVAL_SECONDS": "999",
            },
            f"{cos_dir}:/cos",
        )
        assert result.returncode == 0, result.stderr

        with open(f"{cos_dir}/public/logs.log") as f:
            public = f.read()
        with open(f"{cos_dir}/provider/logs.log") as f:
            private = f.read()

    # Public log: only [PUBLIC]-prefixed lines, prefix stripped.
    assert "public line 1" in public
    assert "public line 2" in public
    assert "private line" not in public
    assert "plain line" not in public
    for tag in ("[PUBLIC]", "[public]"):
        assert tag not in public, f"prefix '{tag}' must be stripped"
    assert "Logs exceeded maximum allowed size" not in public

    # Private log: [PRIVATE] lines (prefix stripped) + plain lines verbatim.
    assert "private line 1" in private
    assert "private line 2" in private
    assert "plain line 1" in private
    assert "plain line 2" in private
    for tag in ("[PRIVATE]", "[private]"):
        assert tag not in private, f"prefix '{tag}' must be stripped"
    assert "public line" not in private
    assert "Logs exceeded maximum allowed size" not in private


@docker_required
def test_wrapper_failure_propagates_exit_code_and_flushes_logs():
    """Wrapper propagates the application's real exit code and flushes logs on failure.

    The EXIT trap must fire even on non-zero exit so no output is lost. This verifies
    both that the exit code is not swallowed by the wrapper and that the log on COS
    contains lines written before the failure.
    """
    app = "printf 'output before failure\\n'; exit 7"
    run_commands = _render_wrapper(["sh", "-c", app])

    with tempfile.TemporaryDirectory(dir=_DOCKER_TMP) as tmp:
        cos_dir = f"{tmp}/cos"
        os.makedirs(f"{cos_dir}/public")
        result = _docker_run(
            run_commands,
            {"PUBLIC_LOG_PATH": "/cos/public/logs.log", "LOG_FLUSH_INTERVAL_SECONDS": "999"},
            f"{cos_dir}:/cos",
        )
        assert result.returncode == 7
        with open(f"{cos_dir}/public/logs.log") as f:
            content = f.read()

    assert "output before failure" in content


# Small limit used by truncation tests — large enough to hold a few lines but
# small enough to be exceeded by 50 lines of ~28 bytes each (~1 400 bytes total).
_SMALL_LOG_LIMIT = 200


@docker_required
def test_custom_wrapper_truncates_log_when_limit_exceeded():
    """Custom wrapper caps the public log at LOG_SIZE_LIMIT_BYTES and prepends a truncation header.

    When the application produces more output than the limit allows, upload_log keeps
    only the last LOG_SIZE_LIMIT_BYTES bytes (tail) and prepends a human-readable
    header. This means early lines are discarded while the most recent lines are kept,
    mirroring the check_logs behaviour in core.utils.
    """
    app = "i=0; while [ $i -lt 50 ]; do printf 'line %04d: some padding text\\n' $i; i=$((i+1)); done"
    run_commands = _render_wrapper(["sh", "-c", app])

    with tempfile.TemporaryDirectory(dir=_DOCKER_TMP) as tmp:
        cos_dir = f"{tmp}/cos"
        os.makedirs(f"{cos_dir}/public")
        result = _docker_run(
            run_commands,
            {
                "PUBLIC_LOG_PATH": "/cos/public/logs.log",
                "LOG_FLUSH_INTERVAL_SECONDS": "999",
                "LOG_SIZE_LIMIT_BYTES": str(_SMALL_LOG_LIMIT),
            },
            f"{cos_dir}:/cos",
        )
        assert result.returncode == 0, result.stderr
        with open(f"{cos_dir}/public/logs.log") as f:
            content = f.read()

    assert "Logs exceeded maximum allowed size" in content
    assert "line 0000" not in content  # early lines dropped
    assert "line 0049" in content  # last lines kept


@docker_required
def test_provider_wrapper_truncates_both_logs_independently_when_limit_exceeded():
    """Provider wrapper caps public and private logs independently at LOG_SIZE_LIMIT_BYTES.

    Each log is truncated by its own upload_log call, so a large private log does not
    affect the public log and vice versa. Both must show the truncation header and
    retain only their most recent lines.
    """
    app = (
        "i=0; while [ $i -lt 50 ]; do"
        "  printf '[PUBLIC] pub line %04d padding\\n' $i;"
        "  printf '[PRIVATE] priv line %04d padding\\n' $i;"
        "  i=$((i+1));"
        " done"
    )
    run_commands = _render_wrapper(["sh", "-c", app], is_provider_function=True)

    with tempfile.TemporaryDirectory(dir=_DOCKER_TMP) as tmp:
        cos_dir = f"{tmp}/cos"
        os.makedirs(f"{cos_dir}/public")
        os.makedirs(f"{cos_dir}/provider")
        result = _docker_run(
            run_commands,
            {
                "PUBLIC_LOG_PATH": "/cos/public/logs.log",
                "PRIVATE_LOG_PATH": "/cos/provider/logs.log",
                "LOG_FLUSH_INTERVAL_SECONDS": "999",
                "LOG_SIZE_LIMIT_BYTES": str(_SMALL_LOG_LIMIT),
            },
            f"{cos_dir}:/cos",
        )
        assert result.returncode == 0, result.stderr
        with open(f"{cos_dir}/public/logs.log") as f:
            public = f.read()
        with open(f"{cos_dir}/provider/logs.log") as f:
            private = f.read()

    assert "Logs exceeded maximum allowed size" in public
    assert "pub line 0000" not in public
    assert "pub line 0049" in public

    assert "Logs exceeded maximum allowed size" in private
    assert "priv line 0000" not in private
    assert "priv line 0049" in private


@docker_required
def test_custom_wrapper_periodic_flush_during_run():
    """Uploader loop copies logs to COS while the job is still running.

    Uses subprocess.Popen (non-blocking) so we can inspect the COS-mounted file
    mid-run. The job prints one line then sleeps for 10s; with an interval of 2s the
    uploader must have fired at least once by the 5s mark. This test specifically
    exercises the start_uploader background loop, not the EXIT-trap final flush.
    """
    app = "printf 'early line\\n'; sleep 10"
    run_commands = _render_wrapper(["sh", "-c", app])

    with tempfile.TemporaryDirectory(dir=_DOCKER_TMP) as tmp:
        cos_dir = f"{tmp}/cos"
        os.makedirs(f"{cos_dir}/public")
        cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{cos_dir}:/cos",
            "-e",
            "PUBLIC_LOG_PATH=/cos/public/logs.log",
            "-e",
            "LOG_FLUSH_INTERVAL_SECONDS=2",
            _DOCKER_IMAGE,
            *run_commands,
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            # After 5s the uploader must have fired at least once (interval=2s)
            # but the job is still running (sleep 10).
            time.sleep(5)
            cos_log = f"{cos_dir}/public/logs.log"
            assert os.path.exists(cos_log), "log not flushed during run"
            with open(cos_log) as f:
                content = f.read()
            assert "early line" in content, f"periodic flush did not upload early lines:\n{content}"
        finally:
            proc.wait(timeout=20)
