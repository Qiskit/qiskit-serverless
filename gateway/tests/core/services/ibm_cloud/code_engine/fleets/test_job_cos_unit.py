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

"""Unit tests for JobCOS and get_cos_client."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest

from core.ibm_cloud.code_engine.ce_client.rest import ApiException
from core.ibm_cloud import get_cos_client
from core.ibm_cloud.clients import COS_PUBLIC_URL_TEMPLATE
from core.ibm_cloud.code_engine.fleets.cos import (
    TASK_STORE_VERSIONS,
    JobCOS,
    queue_prefix,
    task_state_from_key,
)

_IBM_CLOUD_MOD = "core.ibm_cloud"


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


def test_job_cos_head_object() -> None:
    """head_object() delegates to COSClient.head_object."""
    job_cos, mock_cos = _make_job_cos()
    job_cos.head_object(bucket_name="my-bucket", key="some/key")
    mock_cos.head_object.assert_called_once_with(bucket="my-bucket", key="some/key")


def test_job_cos_head_object_raises_on_empty_bucket() -> None:
    """head_object() raises ValueError when bucket_name is empty."""
    job_cos, _ = _make_job_cos()
    with pytest.raises(ValueError, match="bucket_name"):
        job_cos.head_object(bucket_name="", key="some/key")


def test_job_cos_head_object_raises_on_empty_key() -> None:
    """head_object() raises ValueError when key is empty."""
    job_cos, _ = _make_job_cos()
    with pytest.raises(ValueError, match="key"):
        job_cos.head_object(bucket_name="my-bucket", key="")


def test_job_cos_get_presigned_url() -> None:
    """get_presigned_url() delegates to COSClient.generate_presigned_url."""
    job_cos, mock_cos = _make_job_cos()
    mock_cos.generate_presigned_url.return_value = "https://cos.example.com/key?sig=abc"

    url = job_cos.get_presigned_url(bucket_name="my-bucket", key="some/key", expiry=1800)

    mock_cos.generate_presigned_url.assert_called_once_with(bucket="my-bucket", key="some/key", expiry=1800)
    assert url == "https://cos.example.com/key?sig=abc"


def test_job_cos_get_presigned_url_default_expiry() -> None:
    """get_presigned_url() passes default expiry of 3600 to COSClient."""
    job_cos, mock_cos = _make_job_cos()
    mock_cos.generate_presigned_url.return_value = "https://cos.example.com/key?sig=abc"

    job_cos.get_presigned_url(bucket_name="my-bucket", key="some/key")

    _, kwargs = mock_cos.generate_presigned_url.call_args
    assert kwargs["expiry"] == 3600


def test_job_cos_get_presigned_url_raises_on_empty_bucket() -> None:
    """get_presigned_url() raises ValueError when bucket_name is empty."""
    job_cos, _ = _make_job_cos()
    with pytest.raises(ValueError, match="bucket_name"):
        job_cos.get_presigned_url(bucket_name="", key="some/key")


def test_job_cos_get_presigned_url_raises_on_empty_key() -> None:
    """get_presigned_url() raises ValueError when key is empty."""
    job_cos, _ = _make_job_cos()
    with pytest.raises(ValueError, match="key"):
        job_cos.get_presigned_url(bucket_name="my-bucket", key="")


# ---------------------------------------------------------------------------
# get_cos_client tests
# ---------------------------------------------------------------------------


def test_get_cos_client_fetches_hmac_from_ce_secret() -> None:
    """get_cos_client() fetches HMAC credentials from the CE secret."""
    project = _make_mock_project()
    mock_secret = MagicMock()
    mock_secret.data = {"access_key_id": "ak123", "secret_access_key": "sk456"}

    with (
        patch(f"{_IBM_CLOUD_MOD}.settings") as mock_settings,
        patch(f"{_IBM_CLOUD_MOD}.get_ce_auth", return_value=MagicMock()),
        patch(f"{_IBM_CLOUD_MOD}.SecretsAndConfigmapsApi") as mock_secrets_api_cls,
        patch(f"{_IBM_CLOUD_MOD}.COSClient"),
    ):
        mock_settings.IBM_CLOUD_API_KEY = "test-key"
        mock_settings.CE_HMAC_SECRET_NAME = "cos-hmac"
        mock_settings.CE_COS_USE_PUBLIC_ENDPOINT = False
        mock_secrets_api_cls.return_value.get_secret.return_value = mock_secret

        get_cos_client(project)

    mock_secrets_api_cls.return_value.get_secret.assert_called_once_with(project_id="proj-id", name="cos-hmac")


def test_get_cos_client_passes_hmac_creds_to_cos_client() -> None:
    """get_cos_client() passes extracted HMAC credentials to COSClient."""
    project = _make_mock_project()
    mock_secret = MagicMock()
    mock_secret.data = {"access_key_id": "ak123", "secret_access_key": "sk456"}

    with (
        patch(f"{_IBM_CLOUD_MOD}.settings") as mock_settings,
        patch(f"{_IBM_CLOUD_MOD}.get_ce_auth", return_value=MagicMock()),
        patch(f"{_IBM_CLOUD_MOD}.SecretsAndConfigmapsApi") as mock_secrets_api_cls,
        patch(f"{_IBM_CLOUD_MOD}.COSClient") as mock_cos_cls,
    ):
        mock_settings.IBM_CLOUD_API_KEY = "test-key"
        mock_settings.CE_HMAC_SECRET_NAME = "cos-hmac"
        mock_settings.CE_COS_USE_PUBLIC_ENDPOINT = False
        mock_secrets_api_cls.return_value.get_secret.return_value = mock_secret

        get_cos_client(project)

    creds = mock_cos_cls.call_args.kwargs["credentials"]
    assert creds.access_key_id == "ak123"
    assert creds.secret_access_key == "sk456"


def test_get_cos_client_raises_when_ce_secret_not_found() -> None:
    """get_cos_client() raises ValueError when CE secret returns 404."""
    project = _make_mock_project()

    with (
        patch(f"{_IBM_CLOUD_MOD}.settings") as mock_settings,
        patch(f"{_IBM_CLOUD_MOD}.get_ce_auth", return_value=MagicMock()),
        patch(f"{_IBM_CLOUD_MOD}.SecretsAndConfigmapsApi") as mock_secrets_api_cls,
    ):
        mock_settings.IBM_CLOUD_API_KEY = "test-key"
        mock_settings.CE_HMAC_SECRET_NAME = "missing-secret"
        mock_secrets_api_cls.return_value.get_secret.side_effect = ApiException(status=404, reason="Not Found")

        with pytest.raises(ValueError, match="not found"):
            get_cos_client(project)


def test_get_cos_client_raises_when_ce_secret_missing_fields() -> None:
    """get_cos_client() raises ValueError when CE secret lacks required HMAC fields."""
    project = _make_mock_project()
    mock_secret = MagicMock()
    mock_secret.data = {"access_key_id": "ak123"}  # missing secret_access_key

    with (
        patch(f"{_IBM_CLOUD_MOD}.settings") as mock_settings,
        patch(f"{_IBM_CLOUD_MOD}.get_ce_auth", return_value=MagicMock()),
        patch(f"{_IBM_CLOUD_MOD}.SecretsAndConfigmapsApi") as mock_secrets_api_cls,
    ):
        mock_settings.IBM_CLOUD_API_KEY = "test-key"
        mock_settings.CE_HMAC_SECRET_NAME = "incomplete-secret"
        mock_secrets_api_cls.return_value.get_secret.return_value = mock_secret

        with pytest.raises(ValueError, match="missing"):
            get_cos_client(project)


def test_get_cos_client_uses_public_endpoint_when_configured() -> None:
    """get_cos_client() passes public endpoint URL to COSClient when flag is set."""
    project = _make_mock_project(region="us-east")
    mock_secret = MagicMock()
    mock_secret.data = {"access_key_id": "ak", "secret_access_key": "sk"}

    with (
        patch(f"{_IBM_CLOUD_MOD}.settings") as mock_settings,
        patch(f"{_IBM_CLOUD_MOD}.get_ce_auth", return_value=MagicMock()),
        patch(f"{_IBM_CLOUD_MOD}.SecretsAndConfigmapsApi") as mock_secrets_api_cls,
        patch(f"{_IBM_CLOUD_MOD}.COSClient") as mock_cos_cls,
    ):
        mock_settings.IBM_CLOUD_API_KEY = "test-key"
        mock_settings.CE_HMAC_SECRET_NAME = "cos-hmac"
        mock_settings.CE_COS_USE_PUBLIC_ENDPOINT = True
        mock_secrets_api_cls.return_value.get_secret.return_value = mock_secret

        get_cos_client(project)

    endpoint_url = mock_cos_cls.call_args.kwargs["endpoint_url"]
    assert endpoint_url == COS_PUBLIC_URL_TEMPLATE.format(region="us-east")


def test_get_cos_client_raises_when_api_key_missing() -> None:
    """get_cos_client() raises ValueError when IBM_CLOUD_API_KEY is not set."""
    project = _make_mock_project()

    with patch(f"{_IBM_CLOUD_MOD}.settings") as mock_settings:
        mock_settings.IBM_CLOUD_API_KEY = ""
        mock_settings.CE_HMAC_SECRET_NAME = "cos-hmac"

        with pytest.raises(ValueError, match="IBM_CLOUD_API_KEY"):
            get_cos_client(project)


def test_get_cos_client_raises_when_hmac_secret_name_missing() -> None:
    """get_cos_client() raises ValueError when CE_HMAC_SECRET_NAME is not set."""
    project = _make_mock_project()

    with patch(f"{_IBM_CLOUD_MOD}.settings") as mock_settings:
        mock_settings.IBM_CLOUD_API_KEY = "test-key"
        mock_settings.CE_HMAC_SECRET_NAME = ""

        with pytest.raises(ValueError, match="CE_HMAC_SECRET_NAME"):
            get_cos_client(project)


class TestQueuePrefixAndState:
    """The task-store layout helpers, which the status reader depends on."""

    def test_queue_prefix_defaults_to_the_newest_version(self):
        """A writer that names no version writes the layout Code Engine uses now."""
        assert queue_prefix("proj", "fleet") == "ce/proj/fleet/v3/queue/"
        assert TASK_STORE_VERSIONS[0] == "v3"

    def test_queue_prefix_accepts_the_legacy_version(self):
        """Readers walk older versions, so the prefix has to be buildable for them."""
        assert queue_prefix("proj", "fleet", "v2") == "ce/proj/fleet/v2/queue/"

    def test_state_is_the_segment_after_the_prefix(self):
        """Segment orders differ per state, so only the first one may be read.

        Keys are the real shapes observed on a v3 fleet: pending carries a retry
        count, running a worker and two timestamps, succeeded a result code first.
        """
        prefix = queue_prefix("proj", "fleet")
        cases = {
            f"{prefix}pending/000-00000-0/default/0/2026-08-26T19:09:39Z/uuid": "pending",
            f"{prefix}running/fleet-0/2026-08-26T19:10:14Z/2026-08-26T19:09:39Z/000-00000-0/default/uuid": "running",
            f"{prefix}succeeded/exit_0/fleet-0/t2/t1/t0/000-00000-0/default/uuid": "succeeded",
        }
        for key, expected in cases.items():
            assert task_state_from_key(prefix, key) == expected

    def test_state_is_read_whatever_the_version_segment_is(self):
        """The helper never parses the version, so any version works."""
        for version in ("v2", "v3", "v9", "rev-two"):
            prefix = queue_prefix("proj", "fleet", version)
            assert task_state_from_key(prefix, f"{prefix}succeeded/exit_0/rest") == "succeeded"

    def test_key_outside_the_prefix_has_no_state(self):
        """A key from another version must not be read as if it were this one."""
        assert task_state_from_key(queue_prefix("proj", "fleet", "v3"), "ce/proj/fleet/v2/queue/succeeded/0/x") is None

    def test_directory_marker_has_no_state(self):
        """A zero-byte marker for the prefix itself carries nothing."""
        prefix = queue_prefix("proj", "fleet")
        assert task_state_from_key(prefix, prefix) is None

    def test_deeper_segments_cannot_be_mistaken_for_the_state(self):
        """The batch name is user supplied, so it must not be able to forge a state."""
        prefix = queue_prefix("proj", "fleet")
        key = f"{prefix}pending/000-00000-0/succeeded/0/2026-08-26T19:09:39Z/uuid"
        assert task_state_from_key(prefix, key) == "pending"
