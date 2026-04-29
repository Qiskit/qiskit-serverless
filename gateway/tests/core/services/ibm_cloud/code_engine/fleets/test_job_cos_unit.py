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

import io
from unittest.mock import MagicMock, patch

import pytest

from core.ibm_cloud.code_engine.ce_client.rest import ApiException
from core.ibm_cloud.code_engine.fleets.cos import JobCOS


def _make_job_cos(cos_config: dict | None = None) -> tuple[JobCOS, MagicMock]:
    """Return a JobCOS bound to a mock JobHandler with a pre-wired COSClient."""
    mock_job = MagicMock()
    mock_job.cos_config = cos_config or {
        "hmac_secret_name": "cos-hmac-credential",
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


def test_cos_upload_fileobj() -> None:
    """upload_fileobj() delegates to COSClient.upload_fileobj."""
    job_cos, mock_cos = _make_job_cos()
    fileobj = io.BytesIO(b"data")

    job_cos.upload_fileobj(fileobj=fileobj, bucket_name="my-bucket", key="some/key")

    mock_cos.upload_fileobj.assert_called_once_with(fileobj=fileobj, bucket="my-bucket", key="some/key")


def test_cos_get_object_bytes() -> None:
    """get_object_bytes() delegates to COSClient.get_object_bytes and returns bytes."""
    job_cos, mock_cos = _make_job_cos()
    mock_cos.get_object_bytes.return_value = b"result data"

    result = job_cos.get_object_bytes(bucket_name="my-bucket", key="some/key")

    assert result == b"result data"
    mock_cos.get_object_bytes.assert_called_once_with(bucket="my-bucket", key="some/key")


def test_cos_init_fetches_credentials_from_ce_secret() -> None:
    """Public methods trigger lazy COS init that fetches HMAC credentials from CE secret."""
    mock_job = MagicMock()
    mock_job.cos_config = {"hmac_secret_name": "my-secret"}
    mock_job.client_provider.config.region = "us-south"
    job_cos = JobCOS(mock_job)

    mock_secret = MagicMock()
    mock_secret.data = {"access_key_id": "ak2", "secret_access_key": "sk2"}

    with patch("core.ibm_cloud.code_engine.fleets.cos.SecretsAndConfigmapsApi") as mock_api_cls, patch(
        "core.ibm_cloud.code_engine.fleets.cos.COSClient"
    ) as mock_cos_cls:
        mock_api_cls.return_value.get_secret.return_value = mock_secret
        mock_cos_cls.return_value.get_object_bytes.return_value = b"data"
        job_cos.get_object_bytes(bucket_name="b", key="k")

    mock_api_cls.return_value.get_secret.assert_called_once()


def test_cos_raises_when_no_cos_config() -> None:
    """Public methods raise ValueError when cos_config is None."""
    mock_job = MagicMock()
    mock_job.cos_config = None
    job_cos = JobCOS(mock_job)

    with pytest.raises(ValueError, match="COS not configured"):
        job_cos.get_object_bytes(bucket_name="b", key="k")


def test_cos_wait_for_object_raises_when_missing_args() -> None:
    """wait_for_object() raises ValueError when bucket_name or key is missing."""
    job_cos, _ = _make_job_cos()

    with pytest.raises(ValueError, match="bucket_name"):
        job_cos.wait_for_object(bucket_name="", key="k")
    with pytest.raises(ValueError, match="key"):
        job_cos.wait_for_object(bucket_name="b", key="")


def test_cos_delete_object_raises_when_missing_args() -> None:
    """delete_object() raises ValueError when bucket_name or key is missing."""
    job_cos, _ = _make_job_cos()

    with pytest.raises(ValueError, match="bucket_name"):
        job_cos.delete_object(bucket_name="", key="k")
    with pytest.raises(ValueError, match="key"):
        job_cos.delete_object(bucket_name="b", key="")


def test_cos_get_object_bytes_raises_when_missing_args() -> None:
    """get_object_bytes() raises ValueError when bucket_name or key is missing."""
    job_cos, _ = _make_job_cos()

    with pytest.raises(ValueError, match="bucket_name"):
        job_cos.get_object_bytes(bucket_name="", key="k")
    with pytest.raises(ValueError, match="key"):
        job_cos.get_object_bytes(bucket_name="b", key="")


def test_cos_hmac_credentials_extracted_from_secret() -> None:
    """COS client is initialized with HMAC credentials from CE secret."""
    mock_job = MagicMock()
    mock_job.cos_config = {"hmac_secret_name": "my-secret"}
    mock_job.project_id = "proj-id"
    mock_job.client_provider.config.region = "us-south"
    job_cos = JobCOS(mock_job)

    mock_secret = MagicMock()
    mock_secret.data = {"access_key_id": "ak123", "secret_access_key": "sk456"}

    with patch("core.ibm_cloud.code_engine.fleets.cos.SecretsAndConfigmapsApi") as mock_api_cls, patch(
        "core.ibm_cloud.code_engine.fleets.cos.COSClient"
    ) as mock_cos_cls:
        mock_api_cls.return_value.get_secret.return_value = mock_secret
        mock_cos_cls.return_value.get_object_bytes.return_value = b"data"
        job_cos.get_object_bytes(bucket_name="b", key="k")

    creds = mock_cos_cls.call_args.kwargs["credentials"]
    assert creds.access_key_id == "ak123"
    assert creds.secret_access_key == "sk456"


def test_cos_raises_when_ce_secret_not_found() -> None:
    """Public methods raise ValueError when CE secret returns 404."""
    mock_job = MagicMock()
    mock_job.cos_config = {"hmac_secret_name": "missing-secret"}
    mock_job.project_id = "proj-id"
    mock_job.client_provider.config.region = "us-south"
    job_cos = JobCOS(mock_job)

    with patch("core.ibm_cloud.code_engine.fleets.cos.SecretsAndConfigmapsApi") as mock_api_cls:
        mock_api_cls.return_value.get_secret.side_effect = ApiException(status=404, reason="Not Found")
        with pytest.raises(ValueError, match="not found"):
            job_cos.get_object_bytes(bucket_name="b", key="k")


def test_cos_raises_when_ce_secret_missing_fields() -> None:
    """Public methods raise ValueError when CE secret lacks required HMAC fields."""
    mock_job = MagicMock()
    mock_job.cos_config = {"hmac_secret_name": "incomplete-secret"}
    mock_job.project_id = "proj-id"
    mock_job.client_provider.config.region = "us-south"
    job_cos = JobCOS(mock_job)

    mock_secret = MagicMock()
    mock_secret.data = {"access_key_id": "ak123"}  # missing secret_access_key

    with patch("core.ibm_cloud.code_engine.fleets.cos.SecretsAndConfigmapsApi") as mock_api_cls:
        mock_api_cls.return_value.get_secret.return_value = mock_secret
        with pytest.raises(ValueError, match="missing"):
            job_cos.get_object_bytes(bucket_name="b", key="k")
