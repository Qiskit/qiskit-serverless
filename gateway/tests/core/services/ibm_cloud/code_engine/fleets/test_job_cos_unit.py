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

"""Unit tests for JobCOS."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.services.ibm_cloud.code_engine.fleets.cos import JobCOS


def _make_job_cos(cos_config: dict | None = None) -> tuple[JobCOS, MagicMock]:
    """Return a JobCOS bound to a mock JobHandler with a pre-wired COSClient."""
    mock_job = MagicMock()
    mock_job.cos_config = cos_config or {
        "hmac_access_key_id": "ak",
        "hmac_secret_access_key": "sk",
        "bucket_region": "us-south",
    }
    mock_job.client_provider.config.region = "us-south"
    mock_job.project_id = "proj-id"

    job_cos = JobCOS(mock_job)

    # Pre-wire _cos so tests don't need a real IBMCloudClientProvider
    mock_cos = MagicMock()
    job_cos._JobCOS__cos = mock_cos  # noqa: SLF001

    return job_cos, mock_cos


def test_cos_logs_retrieves_from_cos() -> None:
    """logs() retrieves content from COS and returns it as a string."""
    job_cos, mock_cos = _make_job_cos()
    mock_cos.get_object_bytes.return_value = b"log output"
    mock_cos.wait_until_object_exists.return_value = None

    result = job_cos.logs(
        bucket_name="my-bucket",
        log_key="jobs/123/logs.log",
        save_locally=False,
        wait_for_availability=True,
    )

    assert result == "log output"
    mock_cos.get_object_bytes.assert_called_once_with(bucket="my-bucket", key="jobs/123/logs.log")


def test_cos_logs_without_cos_config_raises_error() -> None:
    """logs() raises ValueError when no cos_config is provided."""
    mock_job = MagicMock()
    mock_job.cos_config = None
    job_cos = JobCOS(mock_job)

    with pytest.raises(ValueError, match="COS not configured"):
        job_cos.logs(bucket_name="my-bucket", log_key="jobs/123/logs.log")


def test_cos_logs_waits_for_availability() -> None:
    """logs() calls wait_until_object_exists when wait_for_availability=True."""
    job_cos, mock_cos = _make_job_cos()
    mock_cos.get_object_bytes.return_value = b"content"
    mock_cos.wait_until_object_exists.return_value = None

    job_cos.logs(
        bucket_name="bucket",
        log_key="key",
        save_locally=False,
        wait_for_availability=True,
        timeout=60,
        poll_interval=5,
    )

    mock_cos.wait_until_object_exists.assert_called_once_with(
        bucket="bucket", key="key", timeout_seconds=60, poll_interval=5
    )


def test_cos_wait_for_object() -> None:
    """wait_for_object() delegates to COSClient.wait_until_object_exists."""
    job_cos, mock_cos = _make_job_cos()

    job_cos.wait_for_object(bucket_name="my-bucket", key="some/key", timeout=120, poll_interval=3)

    mock_cos.wait_until_object_exists.assert_called_once_with(
        bucket="my-bucket", key="some/key", timeout_seconds=120, poll_interval=3
    )


def test_cos_delete_object() -> None:
    """delete_object() delegates to COSClient.delete_object."""
    job_cos, mock_cos = _make_job_cos()

    job_cos.delete_object(bucket_name="my-bucket", key="some/key", wait=True, timeout=60, poll_interval=2)

    mock_cos.delete_object.assert_called_once_with(
        bucket="my-bucket", key="some/key", wait=True, timeout_seconds=60, poll_interval=2
    )
