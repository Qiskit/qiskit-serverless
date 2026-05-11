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
COS operations for fleet job artifacts.

:func:`build_cos_client` is the entry point: given a :class:`CodeEngineProject`
it fetches HMAC credentials from the CE secret and returns a ready :class:`JobCOS`.

Example::

    cos = build_cos_client(project)
    cos.upload_fileobj(fileobj=..., bucket_name="my-bucket", key="jobs/123/args.json")
    content = cos.logs(bucket_name="my-bucket", log_key="jobs/123/logs.log")
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from django.conf import settings

from core.ibm_cloud.code_engine.ce_client.api.secrets_and_configmaps_api import SecretsAndConfigmapsApi
from core.ibm_cloud.code_engine.ce_client.rest import ApiException
from core.ibm_cloud.clients import build_ce_auth, COS_PUBLIC_URL_TEMPLATE
from core.ibm_cloud.cos.cos_client import COSClient, CosHmacCredentials

if TYPE_CHECKING:
    from core.models import CodeEngineProject

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


def build_cos_client(project: CodeEngineProject) -> JobCOS:
    """Build a :class:`JobCOS` for the given CE project.

    Reads ``IBM_CLOUD_API_KEY``, ``CE_HMAC_SECRET_NAME``, and
    ``CE_COS_USE_PUBLIC_ENDPOINT`` from Django settings, fetches HMAC
    credentials from the named CE secret, and returns a ready :class:`JobCOS`.

    Args:
        project: Active :class:`CodeEngineProject` whose region and project_id
            are used to authenticate and locate the CE secret.

    Returns:
        Initialized :class:`JobCOS`.

    Raises:
        ValueError: If required settings are missing or the CE secret is not
            found / lacks the expected HMAC fields.
        ApiException: If the CE secrets API call fails for a non-404 reason.
    """
    api_key = settings.IBM_CLOUD_API_KEY
    if not api_key:
        raise ValueError("IBM_CLOUD_API_KEY not configured")

    hmac_secret_name = settings.CE_HMAC_SECRET_NAME
    if not hmac_secret_name:
        raise ValueError("CE_HMAC_SECRET_NAME not configured")

    ce_api_client, client_provider = build_ce_auth(api_key, project.region)

    secrets_api = SecretsAndConfigmapsApi(ce_api_client)
    try:
        secret = secrets_api.get_secret(project_id=project.project_id, name=hmac_secret_name)
    except ApiException as exc:
        if exc.status == 404:
            raise ValueError(f"CE secret {hmac_secret_name!r} not found in project {project.project_id!r}") from exc
        raise

    data: dict[str, Any] = secret.data if isinstance(secret.data, dict) else {}
    access_key_id = data.get("access_key_id", "")
    secret_access_key = data.get("secret_access_key", "")

    if not access_key_id or not secret_access_key:
        raise ValueError(f"CE secret {hmac_secret_name!r} is missing 'access_key_id' or 'secret_access_key'")

    endpoint_url = None
    if getattr(settings, "CE_COS_USE_PUBLIC_ENDPOINT", False):
        endpoint_url = COS_PUBLIC_URL_TEMPLATE.format(region=project.region)

    cos_client = COSClient(
        client_provider=client_provider,
        credentials=CosHmacCredentials(
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
        ),
        bucket_region=project.region,
        endpoint_url=endpoint_url,
    )
    return JobCOS(cos_client)
