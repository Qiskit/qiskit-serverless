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

"""Unit tests for JobCOS and build_cos_client."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest

from core.ibm_cloud.code_engine.ce_client.rest import ApiException
from core.ibm_cloud.code_engine.fleets.cos import JobCOS, build_cos_client

_COS_MOD = "core.ibm_cloud.code_engine.fleets.cos"


def _make_job_cos() -> tuple[JobCOS, MagicMock]:
    """Return a JobCOS bound to a mock COSClient."""
    mock_cos = MagicMock()
    return JobCOS(mock_cos), mock_cos


def _make_mock_project(region: str = "us-south", project_id: str = "proj-id") -> MagicMock:
    project = MagicMock()
    project.region = region
    project.project_id = project_id
    return project


# ---------------------------------------------------------------------------
# JobCOS operation tests
# ---------------------------------------------------------------------------


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


def test_cos_logs_waits_for_availability() -> None:
    """logs() calls wait_until_object_exists when wait_for_availability=True."""
    job_cos, mock_cos = _make_job_cos()
    mock_cos.get_object_bytes.return_value = b"content"

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


# ---------------------------------------------------------------------------
# build_cos_client tests
# ---------------------------------------------------------------------------


def test_build_cos_client_fetches_hmac_from_ce_secret() -> None:
    """build_cos_client() fetches HMAC credentials from the CE secret."""
    project = _make_mock_project()
    mock_secret = MagicMock()
    mock_secret.data = {"access_key_id": "ak123", "secret_access_key": "sk456"}

    with (
        patch(f"{_COS_MOD}.settings") as mock_settings,
        patch(f"{_COS_MOD}.build_ce_auth", return_value=(MagicMock(), MagicMock())),
        patch(f"{_COS_MOD}.SecretsAndConfigmapsApi") as mock_secrets_api_cls,
        patch(f"{_COS_MOD}.COSClient"),
    ):
        mock_settings.IBM_CLOUD_API_KEY = "test-key"
        mock_settings.CE_HMAC_SECRET_NAME = "cos-hmac"
        mock_settings.CE_COS_USE_PUBLIC_ENDPOINT = False
        mock_secrets_api_cls.return_value.get_secret.return_value = mock_secret

        build_cos_client(project)

    mock_secrets_api_cls.return_value.get_secret.assert_called_once_with(project_id="proj-id", name="cos-hmac")


def test_build_cos_client_passes_hmac_creds_to_cos_client() -> None:
    """build_cos_client() passes extracted HMAC credentials to COSClient."""
    project = _make_mock_project()
    mock_secret = MagicMock()
    mock_secret.data = {"access_key_id": "ak123", "secret_access_key": "sk456"}

    with (
        patch(f"{_COS_MOD}.settings") as mock_settings,
        patch(f"{_COS_MOD}.build_ce_auth", return_value=(MagicMock(), MagicMock())),
        patch(f"{_COS_MOD}.SecretsAndConfigmapsApi") as mock_secrets_api_cls,
        patch(f"{_COS_MOD}.COSClient") as mock_cos_cls,
    ):
        mock_settings.IBM_CLOUD_API_KEY = "test-key"
        mock_settings.CE_HMAC_SECRET_NAME = "cos-hmac"
        mock_settings.CE_COS_USE_PUBLIC_ENDPOINT = False
        mock_secrets_api_cls.return_value.get_secret.return_value = mock_secret

        build_cos_client(project)

    creds = mock_cos_cls.call_args.kwargs["credentials"]
    assert creds.access_key_id == "ak123"
    assert creds.secret_access_key == "sk456"


def test_build_cos_client_raises_when_ce_secret_not_found() -> None:
    """build_cos_client() raises ValueError when CE secret returns 404."""
    project = _make_mock_project()

    with (
        patch(f"{_COS_MOD}.settings") as mock_settings,
        patch(f"{_COS_MOD}.build_ce_auth", return_value=(MagicMock(), MagicMock())),
        patch(f"{_COS_MOD}.SecretsAndConfigmapsApi") as mock_secrets_api_cls,
    ):
        mock_settings.IBM_CLOUD_API_KEY = "test-key"
        mock_settings.CE_HMAC_SECRET_NAME = "missing-secret"
        mock_secrets_api_cls.return_value.get_secret.side_effect = ApiException(status=404, reason="Not Found")

        with pytest.raises(ValueError, match="not found"):
            build_cos_client(project)


def test_build_cos_client_raises_when_ce_secret_missing_fields() -> None:
    """build_cos_client() raises ValueError when CE secret lacks required HMAC fields."""
    project = _make_mock_project()
    mock_secret = MagicMock()
    mock_secret.data = {"access_key_id": "ak123"}  # missing secret_access_key

    with (
        patch(f"{_COS_MOD}.settings") as mock_settings,
        patch(f"{_COS_MOD}.build_ce_auth", return_value=(MagicMock(), MagicMock())),
        patch(f"{_COS_MOD}.SecretsAndConfigmapsApi") as mock_secrets_api_cls,
    ):
        mock_settings.IBM_CLOUD_API_KEY = "test-key"
        mock_settings.CE_HMAC_SECRET_NAME = "incomplete-secret"
        mock_secrets_api_cls.return_value.get_secret.return_value = mock_secret

        with pytest.raises(ValueError, match="missing"):
            build_cos_client(project)


def test_build_cos_client_uses_public_endpoint_when_configured() -> None:
    """build_cos_client() passes public endpoint URL to COSClient when flag is set."""
    project = _make_mock_project(region="us-east")
    mock_secret = MagicMock()
    mock_secret.data = {"access_key_id": "ak", "secret_access_key": "sk"}

    with (
        patch(f"{_COS_MOD}.settings") as mock_settings,
        patch(f"{_COS_MOD}.build_ce_auth", return_value=(MagicMock(), MagicMock())),
        patch(f"{_COS_MOD}.SecretsAndConfigmapsApi") as mock_secrets_api_cls,
        patch(f"{_COS_MOD}.COSClient") as mock_cos_cls,
    ):
        mock_settings.IBM_CLOUD_API_KEY = "test-key"
        mock_settings.CE_HMAC_SECRET_NAME = "cos-hmac"
        mock_settings.CE_COS_USE_PUBLIC_ENDPOINT = True
        mock_secrets_api_cls.return_value.get_secret.return_value = mock_secret

        build_cos_client(project)

    endpoint_url = mock_cos_cls.call_args.kwargs["endpoint_url"]
    assert "us-east" in endpoint_url


def test_build_cos_client_raises_when_api_key_missing() -> None:
    """build_cos_client() raises ValueError when IBM_CLOUD_API_KEY is not set."""
    project = _make_mock_project()

    with patch(f"{_COS_MOD}.settings") as mock_settings:
        mock_settings.IBM_CLOUD_API_KEY = ""
        mock_settings.CE_HMAC_SECRET_NAME = "cos-hmac"

        with pytest.raises(ValueError, match="IBM_CLOUD_API_KEY"):
            build_cos_client(project)


def test_build_cos_client_raises_when_hmac_secret_name_missing() -> None:
    """build_cos_client() raises ValueError when CE_HMAC_SECRET_NAME is not set."""
    project = _make_mock_project()

    with patch(f"{_COS_MOD}.settings") as mock_settings:
        mock_settings.IBM_CLOUD_API_KEY = "test-key"
        mock_settings.CE_HMAC_SECRET_NAME = ""

        with pytest.raises(ValueError, match="CE_HMAC_SECRET_NAME"):
            build_cos_client(project)
