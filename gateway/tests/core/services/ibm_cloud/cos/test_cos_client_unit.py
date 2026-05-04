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

"""Unit tests for COSClient."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from ibm_botocore.exceptions import ClientError

from core.ibm_cloud.cos.cos_client import COSClient, CosHmacCredentials


def make_client_error(*, code: str, operation_name: str) -> ClientError:
    """Create an ibm_botocore ClientError with the desired error code."""
    return ClientError({"Error": {"Code": code}}, operation_name)


def _make_client() -> tuple[COSClient, MagicMock]:
    """Return a COSClient and its underlying mocked S3 client."""
    mock_provider = MagicMock()
    mock_s3 = MagicMock()
    mock_provider.get_cos_hmac_client.return_value = mock_s3
    mock_provider.config.region = "us-south"
    creds = CosHmacCredentials(access_key_id="ak", secret_access_key="sk")
    client = COSClient(client_provider=mock_provider, credentials=creds, bucket_region="us-south")
    return client, mock_s3


def test_s3_hmac_is_cached() -> None:
    """get_cos_hmac_client should be called only once across multiple accesses."""
    client, _ = _make_client()
    _ = client._s3_hmac  # noqa: SLF001
    _ = client._s3_hmac  # noqa: SLF001
    client._provider.get_cos_hmac_client.assert_called_once()


def test_endpoint_url_forwarded_to_provider() -> None:
    """COSClient constructed with endpoint_url passes it to get_cos_hmac_client."""
    mock_provider = MagicMock()
    mock_provider.config.region = "us-south"
    creds = CosHmacCredentials(access_key_id="ak", secret_access_key="sk")
    custom_url = "https://s3.private.us-east.cloud-object-storage.appdomain.cloud"

    client = COSClient(
        client_provider=mock_provider,
        credentials=creds,
        bucket_region="us-east",
        endpoint_url=custom_url,
    )
    _ = client._s3_hmac  # noqa: SLF001  trigger lazy init

    mock_provider.get_cos_hmac_client.assert_called_once_with(
        access_key_id="ak",
        secret_access_key="sk",
        bucket_region="us-east",
        endpoint_url=custom_url,
    )


def test_upload_fileobj_calls_s3() -> None:
    """upload_fileobj should delegate to the S3 HMAC client."""
    client, mock_s3 = _make_client()
    fileobj = MagicMock()

    client.upload_fileobj(fileobj=fileobj, bucket="my-bucket", key="some/key")

    mock_s3.upload_fileobj.assert_called_once()
    call_kwargs = mock_s3.upload_fileobj.call_args.kwargs
    assert call_kwargs["Bucket"] == "my-bucket"
    assert call_kwargs["Key"] == "some/key"
    assert call_kwargs["Fileobj"] is fileobj


def test_delete_object_noop_when_missing() -> None:
    """Treat object deletion as idempotent when the object does not exist."""
    client, mock_s3 = _make_client()
    mock_s3.delete_object.side_effect = make_client_error(code="NoSuchKey", operation_name="DeleteObject")

    client.delete_object(bucket="b", key="k", wait=True)

    mock_s3.delete_object.assert_called_once_with(Bucket="b", Key="k")
    mock_s3.get_waiter.assert_not_called()


def test_delete_object_waits_for_deletion() -> None:
    """Wait for object deletion when wait=True."""
    client, mock_s3 = _make_client()
    waiter = MagicMock()
    mock_s3.get_waiter.return_value = waiter

    client.delete_object(bucket="b", key="k", wait=True, timeout_seconds=10, poll_interval=2)

    mock_s3.get_waiter.assert_called_once_with("object_not_exists")
    waiter.wait.assert_called_once_with(Bucket="b", Key="k", WaiterConfig={"Delay": 2, "MaxAttempts": 5})


def test_upload_directory_uploads_files(tmp_path: Path) -> None:
    """Upload all files from a directory with correct key mapping."""
    client, mock_s3 = _make_client()

    base = tmp_path / "data"
    base.mkdir()
    (base / "a.txt").write_text("a", encoding="utf-8")
    sub = base / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("b", encoding="utf-8")

    client.upload_directory(local_dir=str(base), bucket="my-bucket", prefix="providers/p/f/")

    calls = mock_s3.upload_file.call_args_list
    assert len(calls) == 2
    sent_keys = {c.kwargs["Key"] for c in calls}
    assert "providers/p/f/a.txt" in sent_keys
    assert "providers/p/f/sub/b.txt" in sent_keys


def test_upload_folder_is_alias(tmp_path: Path) -> None:
    """upload_folder delegates to upload_directory."""
    client, mock_s3 = _make_client()
    base = tmp_path / "data"
    base.mkdir()
    (base / "file.json").write_text("{}", encoding="utf-8")

    client.upload_folder(local_dir=str(base), bucket="my-bucket", prefix="providers/p/f/")

    mock_s3.upload_file.assert_called_once()
    assert mock_s3.upload_file.call_args.kwargs["Key"] == "providers/p/f/file.json"


def test_download_all_fileobj_downloads_all(tmp_path: Path) -> None:
    """Download all objects under a prefix and preserve relative paths."""
    client, mock_s3 = _make_client()

    paginator = MagicMock()
    paginator.paginate.return_value = [
        {"Contents": [{"Key": "users/u/runs/j/arguments.json"}]},
        {"Contents": [{"Key": "users/u/runs/j/results.json"}]},
    ]
    mock_s3.get_paginator.return_value = paginator

    def download_side_effect(**kwargs: object) -> None:
        fileobj = kwargs.get("Fileobj")
        if callable(getattr(fileobj, "write", None)):
            fileobj.write(b"ok")

    mock_s3.download_fileobj.side_effect = download_side_effect

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    files = client.download_all_fileobj(bucket="b", prefix="users/u/runs/j", local_dir=str(out_dir))

    assert len(files) == 2
    assert (out_dir / "arguments.json").exists()
    assert (out_dir / "results.json").exists()
    paginator.paginate.assert_called_once_with(Bucket="b", Prefix="users/u/runs/j/")


def test_wait_until_object_exists_succeeds_immediately() -> None:
    """Return immediately when head_object succeeds on the first call."""
    client, mock_s3 = _make_client()
    mock_s3.head_object.return_value = {}

    client.wait_until_object_exists(bucket="b", key="k", timeout_seconds=10, poll_interval=2)

    mock_s3.head_object.assert_called_once_with(Bucket="b", Key="k")


def test_wait_until_object_exists_retries_on_404() -> None:
    """Retry head_object when the object does not yet exist."""
    client, mock_s3 = _make_client()
    not_found = ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
    mock_s3.head_object.side_effect = [not_found, not_found, {}]

    with patch("time.time", side_effect=[0, 1, 3, 5]), patch("time.sleep") as mock_sleep:
        client.wait_until_object_exists(bucket="b", key="k", timeout_seconds=10, poll_interval=2)

    assert mock_s3.head_object.call_count == 3
    assert mock_sleep.call_count == 2


def test_wait_until_object_exists_raises_timeout() -> None:
    """Raise TimeoutError when the object never appears within the deadline."""
    client, mock_s3 = _make_client()
    not_found = ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
    mock_s3.head_object.side_effect = not_found

    with patch("time.time", side_effect=[0, 11]), patch("time.sleep"):
        with pytest.raises(TimeoutError, match="did not become available"):
            client.wait_until_object_exists(bucket="b", key="k", timeout_seconds=10, poll_interval=2)


def test_get_object_stream_missing_body_raises() -> None:
    """Raise RuntimeError when get_object response does not include Body."""
    client, mock_s3 = _make_client()
    mock_s3.get_object.return_value = {}

    with pytest.raises(RuntimeError):
        client.get_object_stream(bucket="b", key="k")


def test_get_object_bytes_reads_body() -> None:
    """Read object bytes from a streaming body."""
    client, mock_s3 = _make_client()
    body = MagicMock()
    body.read.return_value = b"payload"
    mock_s3.get_object.return_value = {"Body": body}

    data = client.get_object_bytes(bucket="b", key="k")

    assert data == b"payload"
    mock_s3.get_object.assert_called_once_with(Bucket="b", Key="k")
