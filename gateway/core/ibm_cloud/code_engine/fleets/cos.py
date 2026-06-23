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

"""COS operations for fleet job artifacts."""

from __future__ import annotations

import logging

from core.ibm_cloud.cos.cos_client import COSClient

logger = logging.getLogger("FleetHandler")


class JobCOS:
    """COS operations wrapper for fleet job artifacts."""

    def __init__(self, cos_client: COSClient) -> None:
        self._cos = cos_client

    def wait_for_object(
        self,
        *,
        bucket_name: str,
        key: str,
        timeout: int = 180,
        poll_interval: int = 2,
    ) -> None:
        """Wait until an object exists in COS.

        Args:
            bucket_name: COS bucket name.
            key: Object key.
            timeout: Maximum wait time in seconds.
            poll_interval: Poll interval in seconds.

        Raises:
            ValueError: If bucket_name or key is missing.
            TimeoutError: If the object does not appear in time.
        """
        if not bucket_name:
            raise ValueError("bucket_name is required.")
        if not key:
            raise ValueError("key is required.")

        self._cos.wait_until_object_exists(
            bucket=bucket_name,
            key=key,
            timeout_seconds=timeout,
            poll_interval=poll_interval,
        )

    def delete_object(
        self,
        *,
        bucket_name: str,
        key: str,
        wait: bool = True,
        timeout: int = 180,
        poll_interval: int = 2,
    ) -> None:
        """Delete an object from COS.

        Args:
            bucket_name: COS bucket name.
            key: Object key.
            wait: Whether to wait until deletion is confirmed.
            timeout: Maximum wait time in seconds.
            poll_interval: Poll interval in seconds.

        Raises:
            ValueError: If bucket_name or key is missing.
        """
        if not bucket_name:
            raise ValueError("bucket_name is required.")
        if not key:
            raise ValueError("key is required.")

        self._cos.delete_object(
            bucket=bucket_name,
            key=key,
            wait=wait,
            timeout_seconds=timeout,
            poll_interval=poll_interval,
        )

    def upload_fileobj(
        self,
        *,
        fileobj: object,
        bucket_name: str,
        key: str,
    ) -> None:
        """Upload a file-like object to COS.

        Args:
            fileobj: Binary file-like object to upload.
            bucket_name: COS bucket name.
            key: Object key.

        Raises:
            ValueError: If bucket_name or key is missing.
        """
        if not bucket_name:
            raise ValueError("bucket_name is required.")
        if not key:
            raise ValueError("key is required.")

        self._cos.upload_fileobj(fileobj=fileobj, bucket=bucket_name, key=key)

    def get_object_bytes(self, *, bucket_name: str, key: str) -> bytes:
        """Retrieve an object fully into memory.

        Args:
            bucket_name: COS bucket name.
            key: Object key.

        Returns:
            Object content as bytes.
        """
        if not bucket_name:
            raise ValueError("bucket_name is required.")
        if not key:
            raise ValueError("key is required.")

        return self._cos.get_object_bytes(bucket=bucket_name, key=key)

    def list_keys(
        self,
        *,
        bucket_name: str,
        prefix: str | None = None,
    ) -> list[str]:
        """List object keys in a COS bucket.

        Args:
            bucket_name: COS bucket name.
            prefix: Optional key prefix to filter results.

        Returns:
            List of object keys.
        """
        return self._cos.list_keys(bucket=bucket_name, prefix=prefix)

    def list_with_metadata(
        self,
        *,
        bucket_name: str,
        prefix: str,
    ) -> list[dict]:
        """List objects under a prefix with size and last_modified metadata.

        Args:
            bucket_name: COS bucket name.
            prefix: Key prefix to filter results.

        Returns:
            List of dicts with keys ``key``, ``size``, ``last_modified``.

        Raises:
            ValueError: If bucket_name is missing.
        """
        if not bucket_name:
            raise ValueError("bucket_name is required.")
        return self._cos.list_with_metadata(bucket=bucket_name, prefix=prefix)

    def head_object(self, *, bucket_name: str, key: str) -> None:
        """Check that an object exists in COS.

        Args:
            bucket_name: COS bucket name.
            key: Object key.

        Raises:
            ValueError: If bucket_name or key is missing.
            ClientError: If the object does not exist or an unexpected error occurs.
        """
        if not bucket_name:
            raise ValueError("bucket_name is required.")
        if not key:
            raise ValueError("key is required.")
        self._cos.head_object(bucket=bucket_name, key=key)

    def get_presigned_url(self, *, bucket_name: str, key: str, expiry: int = 3600) -> str:
        """Generate a presigned GET URL for an object.

        Args:
            bucket_name: COS bucket name.
            key: Object key.
            expiry: URL validity in seconds (default 3600).

        Returns:
            Presigned URL string.

        Raises:
            ValueError: If bucket_name or key is missing.
        """
        if not bucket_name:
            raise ValueError("bucket_name is required.")
        if not key:
            raise ValueError("key is required.")
        return self._cos.generate_presigned_url(bucket=bucket_name, key=key, expiry=expiry)
