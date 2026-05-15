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
from datetime import datetime
from pathlib import Path

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

    def logs(
        self,
        *,
        bucket_name: str,
        log_key: str,
        save_locally: bool = False,
        local_dir: str = "results",
        wait_for_availability: bool = True,
        timeout: int = 300,
        poll_interval: int = 5,
    ) -> str:
        """Retrieve a log file from COS.

        Args:
            bucket_name: COS bucket name containing the log object.
            log_key: Full object key of the log file.
            save_locally: If True, save the log file locally.
            local_dir: Directory where logs are saved when save_locally is enabled.
            wait_for_availability: If True, wait for the log file to appear in COS.
            timeout: Maximum time to wait for the log file, in seconds.
            poll_interval: Time between polling attempts, in seconds.

        Returns:
            The log content as a string.

        Raises:
            ValueError: If bucket_name or log_key is missing.
            RuntimeError: If the log file cannot be retrieved.
            TimeoutError: If the log file is not available within timeout.
        """
        if not bucket_name:
            raise ValueError("bucket_name is required.")
        if not log_key:
            raise ValueError("log_key is required.")

        if wait_for_availability:
            self._cos.wait_until_object_exists(
                bucket=bucket_name,
                key=log_key,
                timeout_seconds=timeout,
                poll_interval=poll_interval,
            )

        try:
            log_content_bytes = self._cos.get_object_bytes(bucket=bucket_name, key=log_key)
            log_content = log_content_bytes.decode("utf-8")

            if save_locally:
                local_path = Path(local_dir)
                local_path.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_key = log_key.strip("/").replace("/", "_")
                local_filepath = local_path / f"{bucket_name}_{safe_key}_{timestamp}"
                with open(local_filepath, "wb") as file_obj:
                    file_obj.write(log_content_bytes)

            return log_content

        except TimeoutError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"Failed to retrieve log file '{log_key}' from COS bucket '{bucket_name}': {exc}"
            ) from exc
