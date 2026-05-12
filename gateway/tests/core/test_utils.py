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

"""Unit tests for core.utils.check_logs."""

import logging
from unittest.mock import Mock

import pytest
from django.conf import settings

from core.models import Job
from core.utils import check_logs


def _make_job(status=Job.RUNNING, job_id="test-job-id"):
    job = Mock()
    job.id = job_id
    job.status = status
    return job


def test_check_logs_returns_empty_for_none():
    assert check_logs(None, _make_job()) == ""


def test_check_logs_returns_empty_for_empty_string():
    assert check_logs("", _make_job()) == ""


def test_check_logs_returns_logs_unchanged_when_within_limit():
    logs = "a" * (settings.FUNCTIONS_LOGS_SIZE_LIMIT - 1)
    assert check_logs(logs, _make_job()) == logs


def test_check_logs_failed_job_default_message():
    """A FAILED job with no logs gets a default error message."""
    job = _make_job(status=Job.FAILED)
    result = check_logs(None, job)
    assert "failed due to an internal error" in result


def test_check_logs_truncates_oversized_logs():
    """Logs exceeding the size limit are truncated, keeping the newest (tail) content."""
    max_bytes = settings.FUNCTIONS_LOGS_SIZE_LIMIT
    logs = "a" * (max_bytes + 100)
    result = check_logs(logs, _make_job())
    assert result.startswith("[Logs exceeded")
    # The truncated body is the last max_bytes characters of the original
    assert result.endswith("a" * max_bytes)


def test_check_logs_warning_shows_mb_not_raw_bytes(caplog):
    """The oversized-log warning must show human-readable MB values, not raw byte counts.

    Regression test: before the fix the format string used %s with raw byte values,
    producing messages like '1157317193 MB > 52428800 MB' instead of '~1103.6 MB > 50.0 MB'.
    """
    max_bytes = settings.FUNCTIONS_LOGS_SIZE_LIMIT
    logs = "x" * (max_bytes + 1)

    with caplog.at_level(logging.WARNING, logger="core"):
        check_logs(logs, _make_job())

    assert caplog.records, "Expected a warning to be logged"
    message = caplog.records[0].getMessage()

    # The raw byte count must not appear — it would be a 8-digit+ integer with no decimal
    assert str(max_bytes) not in message
    assert str(max_bytes + 1) not in message
    # The value must be expressed in MB (float with one decimal place)
    expected_mb = f"{(max_bytes + 1) / (1024 ** 2):.1f} MB"
    assert expected_mb in message
