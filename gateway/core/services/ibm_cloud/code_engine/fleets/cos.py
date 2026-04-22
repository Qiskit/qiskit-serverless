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
COS sub-manager for fleet job artifacts.

Provides :class:`JobCOS`, which wraps :class:`COSClient` for operations on
COS objects associated with a fleet job: waiting for objects, deleting objects,
listing keys, and retrieving log files.

HMAC credentials are resolved in priority order:

1. ``hmac_access_key_id`` + ``hmac_secret_access_key`` supplied directly in
   ``cos_config`` — used as-is, no CE API call.
2. ``hmac_secret_name`` supplied in ``cos_config`` — credentials are fetched
   from the named Code Engine secret via the Secrets API (same project).
3. ``hmac_access_key_id`` alone in ``cos_config`` — ``hmac_secret_access_key``
   is discovered from the CE secret whose name matches ``hmac_access_key_id``.

Access via the parent handler::

    handler = FleetHandler(client_provider=provider, project_id=project_id,
                           cos_config={...})
    handler.cos.wait_for_object(bucket_name="my-bucket", key="logs/run.log")
    content = handler.cos.logs(bucket_name="my-bucket", log_key="logs/run.log")
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from swagger_client.api.secrets_and_configmaps_api import SecretsAndConfigmapsApi
from swagger_client.rest import ApiException

from core.services.ibm_cloud.cos.cos_client import COSClient, CosHmacCredentials

if TYPE_CHECKING:
    from core.services.ibm_cloud.code_engine.fleets.fleet_handler import FleetHandler

logger = logging.getLogger("FleetHandler")


class JobCOS:
    """
    Sub-manager for COS operations on fleet job artifacts.

    Instances are created automatically by :class:`FleetHandler` and
    should not be instantiated directly.
    """

    def __init__(self, job: FleetHandler) -> None:
        self._job = job
        self.__cos: COSClient | None = None

    def _get_hmac_from_ce_secret(self, secret_name: str) -> CosHmacCredentials:
        """Fetch HMAC credentials from a Code Engine secret.

        Args:
            secret_name: Name of the CE secret containing HMAC credentials.

        Returns:
            :class:`CosHmacCredentials` extracted from the secret data.

        Raises:
            ValueError: If the secret does not exist or lacks valid HMAC data.
        """
        secrets_api = SecretsAndConfigmapsApi(self._job._client)  # pylint: disable=protected-access
        try:
            secret = secrets_api.get_secret(
                project_id=self._job.project_id,
                name=secret_name,
            )
        except ApiException as exc:
            if exc.status == 404:
                raise ValueError(f"CE secret {secret_name!r} not found in project {self._job.project_id!r}.") from exc
            raise

        data: dict[str, Any] = secret.data if isinstance(secret.data, dict) else {}
        access_key_id = data.get("access_key_id", "")
        secret_access_key = data.get("secret_access_key", "")

        if not access_key_id or not secret_access_key:
            raise ValueError(
                f"CE secret {secret_name!r} exists but is missing 'access_key_id' or 'secret_access_key' fields."
            )

        return CosHmacCredentials(
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
        )

    @property
    def _cos(self) -> COSClient:
        """Lazily initialize and return the COSClient.

        HMAC credentials are resolved in priority order:
        1. Both ``hmac_access_key_id`` and ``hmac_secret_access_key`` provided directly.
        2. ``hmac_secret_name`` provided — fetch both keys from the named CE secret.
        3. ``hmac_access_key_id`` alone — fetch ``hmac_secret_access_key`` from the
           CE secret whose name matches the key ID.

        Returns:
            Initialized :class:`COSClient` bound to the resolved HMAC credentials.

        Raises:
            ValueError: If ``cos_config`` is missing or credentials cannot be resolved.
        """
        if self.__cos is not None:
            return self.__cos

        cos_config = self._job.cos_config
        if not cos_config:
            raise ValueError("COS not configured. Pass cos_config to FleetHandler constructor.")

        hmac_access_key_id = cos_config.get("hmac_access_key_id")
        hmac_secret_access_key = cos_config.get("hmac_secret_access_key")
        hmac_secret_name = cos_config.get("hmac_secret_name")
        bucket_region = cos_config.get("bucket_region", self._job.client_provider.config.region)

        if hmac_access_key_id and hmac_secret_access_key:
            # Priority 1: both keys provided directly — no CE API call needed.
            creds = CosHmacCredentials(
                access_key_id=hmac_access_key_id,
                secret_access_key=hmac_secret_access_key,
            )
        elif hmac_secret_name:
            # Priority 2: fetch both keys from the named CE secret.
            logger.debug("Fetching HMAC credentials from CE secret %r", hmac_secret_name)
            creds = self._get_hmac_from_ce_secret(hmac_secret_name)
        elif hmac_access_key_id:
            # Priority 3: key ID provided without secret — fetch from the CE secret
            # whose name matches the key ID.
            logger.debug(
                "hmac_secret_access_key not provided — fetching from CE secret %r",
                hmac_access_key_id,
            )
            creds = self._get_hmac_from_ce_secret(hmac_access_key_id)
        else:
            raise ValueError(
                "cos_config must include at least 'hmac_access_key_id'. "
                "Provide 'hmac_secret_access_key' directly, 'hmac_secret_name' to fetch "
                "credentials from a named CE secret, or rely on auto-discovery by "
                "setting only 'hmac_access_key_id' (the CE secret name must match)."
            )

        self.__cos = COSClient(
            client_provider=self._job.client_provider,
            credentials=creds,
            bucket_region=bucket_region,
        )
        return self.__cos

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
