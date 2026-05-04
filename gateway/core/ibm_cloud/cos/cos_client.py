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
IBM Cloud Object Storage (COS) bucket client.

Provides :class:`COSClient` for bucket-scoped object operations built on
the IBM COS S3-compatible API (``ibm_boto3``). Buckets are assumed to be
pre-existing — no provisioning or bucket creation is performed here.

Features:
    - Delete a single object (with waiter support)
    - Upload a folder (directory tree) or file-like object
    - Download file-like objects (single or by prefix)
    - Wait until object exists
    - Stream or fully read objects
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ibm_boto3.s3.transfer import TransferConfig
from ibm_botocore.exceptions import ClientError

if TYPE_CHECKING:
    from core.ibm_cloud.clients import IBMCloudClientProvider

logger = logging.getLogger("gateway.ibm_cloud.cos")


@dataclass(frozen=True)
class CosHmacCredentials:
    """HMAC credentials for COS S3-compatible access."""

    access_key_id: str
    secret_access_key: str


class COSClient:
    """IBM Cloud Object Storage bucket client.

    Wraps ``ibm_boto3`` for object operations against pre-existing buckets.
    The underlying S3 client is created lazily on first use and cached.
    """

    def __init__(
        self,
        *,
        client_provider: IBMCloudClientProvider,
        credentials: CosHmacCredentials,
        bucket_region: str | None = None,
        endpoint_url: str | None = None,
        max_threads: int = 8,
    ) -> None:
        """
        Initialize the COS client.

        Args:
            client_provider: Initialized IBM Cloud client provider.
            credentials: HMAC credentials for S3-compatible access.
            bucket_region: Bucket endpoint region. Defaults to the provider region.
            endpoint_url: Override the COS S3 endpoint URL. Use the private endpoint
                (e.g. ``https://s3.private.us-east.cloud-object-storage.appdomain.cloud``)
                when running inside IBM Cloud to avoid public internet egress.
            max_threads: Multipart transfer concurrency limit.
        """
        self._provider = client_provider
        self._credentials = credentials
        self._bucket_region = bucket_region or client_provider.config.region
        self._endpoint_url = endpoint_url
        self._max_threads = max_threads
        self._s3: Any = None
        self._transfer_config: TransferConfig | None = None

    @property
    def _s3_hmac(self) -> Any:
        """Return cached S3 HMAC client, creating it on first access."""
        if self._s3 is None:
            self._s3 = self._provider.get_cos_hmac_client(
                access_key_id=self._credentials.access_key_id,
                secret_access_key=self._credentials.secret_access_key,
                bucket_region=self._bucket_region,
                endpoint_url=self._endpoint_url,
            )
        return self._s3

    @property
    def _transfer(self) -> TransferConfig:
        """Return cached TransferConfig, creating it on first access."""
        if self._transfer_config is None:
            self._transfer_config = TransferConfig(
                max_concurrency=self._max_threads,
                multipart_threshold=8 * 1024 * 1024,
                multipart_chunksize=8 * 1024 * 1024,
                use_threads=True,
            )
        return self._transfer_config

    def delete_object(
        self,
        *,
        bucket: str,
        key: str,
        wait: bool = True,
        timeout_seconds: int = 180,
        poll_interval: int = 2,
    ) -> None:
        """
        Delete a single object.

        Args:
            bucket: Bucket name.
            key: Object key.
            wait: Whether to wait until the object no longer exists.
            timeout_seconds: Maximum wait time in seconds.
            poll_interval: Poll interval in seconds.

        Raises:
            ClientError: If deletion fails unexpectedly.
        """
        s3 = self._s3_hmac

        try:
            logger.debug("Deleting object %s/%s", bucket, key)
            s3.delete_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in {"404", "NoSuchKey", "NotFound"}:
                logger.debug("Object %s/%s already deleted", bucket, key)
                return
            raise

        if wait:
            try:
                s3.get_waiter("object_not_exists").wait(
                    Bucket=bucket,
                    Key=key,
                    WaiterConfig={
                        "Delay": poll_interval,
                        "MaxAttempts": max(1, timeout_seconds // poll_interval),
                    },
                )
                logger.debug("Confirmed object %s/%s deleted", bucket, key)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code in {"404", "NoSuchKey", "NotFound"}:
                    return
                raise

    def upload_directory(self, *, local_dir: str, bucket: str, prefix: str = "") -> None:
        """
        Upload all files from a local directory.

        Args:
            local_dir: Path to local directory.
            bucket: Target bucket name.
            prefix: Optional object key prefix.

        Raises:
            RuntimeError: If the directory does not exist.
            ClientError: If upload fails.
        """
        s3 = self._s3_hmac
        base = Path(local_dir)

        if not base.exists():
            raise RuntimeError(f"Local directory does not exist: {local_dir}")

        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(base).as_posix()
            key = f"{prefix}{rel}" if prefix else rel
            logger.debug("Uploading %s to %s/%s", path, bucket, key)
            s3.upload_file(Filename=str(path), Bucket=bucket, Key=key, Config=self._transfer)

    def upload_folder(self, *, local_dir: str, bucket: str, prefix: str = "") -> None:
        """Alias for :meth:`upload_directory`."""
        self.upload_directory(local_dir=local_dir, bucket=bucket, prefix=prefix)

    def upload_fileobj(
        self,
        *,
        fileobj: object,
        bucket: str,
        key: str,
        callback: Callable[[int], None] | None = None,
    ) -> None:
        """
        Upload a file-like object.

        Args:
            fileobj: Binary file-like object.
            bucket: Target bucket name.
            key: Object key.
            callback: Optional progress callback receiving bytes transferred.

        Raises:
            ClientError: If upload fails.
        """
        self._s3_hmac.upload_fileobj(
            Fileobj=fileobj,
            Bucket=bucket,
            Key=key,
            Callback=callback,
            Config=self._transfer,
        )

    def download_fileobj(
        self,
        *,
        bucket: str,
        key: str,
        fileobj: object,
        callback: Callable[[int], None] | None = None,
    ) -> None:
        """
        Download an object into a file-like object.

        Args:
            bucket: Bucket name.
            key: Object key.
            fileobj: Writable binary file-like object.
            callback: Optional progress callback receiving bytes transferred.

        Raises:
            ClientError: If download fails.
        """
        self._s3_hmac.download_fileobj(
            Bucket=bucket,
            Key=key,
            Fileobj=fileobj,
            Callback=callback,
            Config=self._transfer,
        )

    def download_all_fileobj(
        self,
        *,
        bucket: str,
        prefix: str,
        local_dir: str,
        callback: Callable[[int], None] | None = None,
    ) -> list[str]:
        """
        Download all objects under a key prefix into a local directory.

        Args:
            bucket: Bucket name.
            prefix: Key prefix to download.
            local_dir: Local directory where objects will be saved.
            callback: Optional progress callback receiving bytes transferred.

        Returns:
            List of local file paths created.

        Raises:
            ClientError: If listing or download fails.
        """
        s3 = self._s3_hmac
        base = Path(local_dir)
        base.mkdir(parents=True, exist_ok=True)

        norm_prefix = prefix.lstrip("/")
        if norm_prefix and not norm_prefix.endswith("/"):
            norm_prefix = f"{norm_prefix}/"

        paginator = s3.get_paginator("list_objects_v2")
        downloaded: list[str] = []

        for page in paginator.paginate(Bucket=bucket, Prefix=norm_prefix):
            for obj in page.get("Contents") or []:
                key = obj.get("Key") if isinstance(obj, dict) else None
                if not isinstance(key, str) or not key:
                    continue

                rel = key[len(norm_prefix) :] if norm_prefix and key.startswith(norm_prefix) else key
                if not rel or rel.endswith("/"):
                    continue

                out_path = base / rel
                out_path.parent.mkdir(parents=True, exist_ok=True)

                logger.debug("Downloading %s/%s to %s", bucket, key, out_path)
                with open(out_path, "wb") as f:
                    s3.download_fileobj(Bucket=bucket, Key=key, Fileobj=f, Callback=callback, Config=self._transfer)
                downloaded.append(str(out_path))

        return downloaded

    def wait_until_object_exists(
        self,
        *,
        bucket: str,
        key: str,
        timeout_seconds: int = 180,
        poll_interval: int = 2,
    ) -> None:
        """
        Wait until an object exists in COS.

        Args:
            bucket: Bucket name.
            key: Object key.
            timeout_seconds: Maximum wait time in seconds.
            poll_interval: Poll interval in seconds.

        Raises:
            TimeoutError: If the object does not appear within timeout_seconds.
            ClientError: If an unexpected S3 error occurs.
        """
        s3 = self._s3_hmac
        deadline = time.time() + timeout_seconds
        last_exc = None

        while time.time() < deadline:
            try:
                s3.head_object(Bucket=bucket, Key=key)
                return
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code in {"404", "NoSuchKey", "NotFound"}:
                    last_exc = exc
                    time.sleep(poll_interval)
                    continue
                raise

        raise TimeoutError(
            f"Object '{key}' did not become available in bucket '{bucket}' within {timeout_seconds} seconds"
        ) from last_exc

    def list_keys(self, *, bucket: str, prefix: str | None = None) -> list[str]:
        """
        List object keys in a bucket.

        Args:
            bucket: Bucket name.
            prefix: Optional key prefix to filter results.

        Returns:
            List of object keys.
        """
        paginator = self._s3_hmac.get_paginator("list_objects_v2")
        paginate_kwargs: dict = {"Bucket": bucket}
        if prefix:
            paginate_kwargs["Prefix"] = prefix

        keys: list[str] = []
        for page in paginator.paginate(**paginate_kwargs):
            for obj in page.get("Contents") or []:
                obj_key = obj.get("Key")
                if isinstance(obj_key, str):
                    keys.append(obj_key)
        return keys

    def get_object_stream(self, *, bucket: str, key: str) -> Any:
        """
        Retrieve object as a streaming body.

        Args:
            bucket: Bucket name.
            key: Object key.

        Returns:
            Streaming body object.

        Raises:
            RuntimeError: If the response does not contain a body.
            ClientError: If retrieval fails.
        """
        response = self._s3_hmac.get_object(Bucket=bucket, Key=key)
        body = response.get("Body")
        if body is None:
            raise RuntimeError("get_object response missing Body")
        return body

    def get_object_bytes(self, *, bucket: str, key: str) -> bytes:
        """
        Retrieve object fully into memory.

        Args:
            bucket: Bucket name.
            key: Object key.

        Returns:
            Object content as bytes.

        Raises:
            RuntimeError: If the response does not contain a body.
            ClientError: If retrieval fails.
        """
        return self.get_object_stream(bucket=bucket, key=key).read()
