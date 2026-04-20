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
IBM Cloud Clients module.

Provides :class:`IBMCloudClientProvider`, responsible for IBM Cloud
authentication and COS client creation.

Only the minimal surface needed by :class:`FleetsJobHandler` and the COS
layer is included here:

- IAM authentication and JWT token decoding
- COS HMAC S3-compatible client factory

Example::

    from core.services.ibm_cloud.clients import IBMCloudClientProvider

    provider = IBMCloudClientProvider(api_key="YOUR_API_KEY", region="us-south")

    # HMAC client: uploads/downloads/streaming
    s3 = provider.get_cos_hmac_client(
        access_key_id="ACCESS_KEY",
        secret_access_key="SECRET_KEY",
        bucket_region="us-south",
    )
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from ibm_boto3 import client as ibm_boto3_client
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator

IAM_PROD_URL = "https://iam.cloud.ibm.com"
IAM_TEST_URL = "https://iam.test.cloud.ibm.com"

COS_URL_TEMPLATE = "https://s3.{region}.cloud-object-storage.appdomain.cloud"
CODE_ENGINE_URL_TEMPLATE = "https://api.{region}.codeengine.cloud.ibm.com/v2"

DEFAULT_REGION = "us-south"

logger = logging.getLogger("gateway.ibm_cloud.clients_provider")


def decode_jwt(token: str) -> dict[str, Any]:
    """
    Decode a JWT token and return its payload as a dictionary.

    Args:
        token: JWT string in the standard format ``header.payload.signature``.

    Returns:
        The decoded payload of the JWT as a dictionary.

    Raises:
        IndexError: If the JWT string is malformed and does not contain three parts.
        json.JSONDecodeError: If the decoded payload is not valid JSON.
        binascii.Error: If the base64 decoding fails.
    """
    payload = token.split(".")[1]
    padded = payload + "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


@dataclass(frozen=True)
class EndpointConfig:
    """Resolved service endpoints derived from staging mode and region."""

    staging: bool
    region: str
    iam_url: str
    cos_url: str
    code_engine_url: str


class AuthState:
    """Authentication state derived from the IAM token.

    ``token`` is a lazy property — each access calls the SDK token manager,
    which returns the cached token or fetches a new one if it is near expiry.
    This means callers always get a valid bearer token without any manual
    refresh logic.
    """

    def __init__(
        self,
        authenticator: IAMAuthenticator,
        iam_id: str,
        account_id: str,
        api_key: str,
    ) -> None:
        self.authenticator = authenticator
        self.iam_id = iam_id
        self.account_id = account_id
        self.api_key = api_key

    @property
    def token(self) -> str:
        """Return a valid IAM bearer token, refreshing automatically when near expiry."""
        return self.authenticator.token_manager.get_token()


@dataclass
class ClientCache:
    """Per-credential COS client cache."""

    # HMAC clients cached by (bucket_region, access_key_id)
    cos_hmac: dict[tuple[str, str], Any] = field(default_factory=dict)


class IBMCloudClientProvider:
    """
    Provider for IBM Cloud SDK clients.

    Handles IAM authentication and creation of COS S3-compatible clients.
    HMAC clients are created on demand and cached for reuse.

    Supports staging mode for the IAM endpoint.
    """

    def __init__(
        self,
        api_key: str,
        *,
        staging: bool = False,
        region: str | None = None,
    ) -> None:
        """
        Initialize the IBM Cloud client provider.

        Args:
            api_key: IBM Cloud API key.
            staging: If True, use the staging IAM endpoint.
            region: Default region for regional services. Defaults to ``"us-south"``.

        Raises:
            RuntimeError: If authentication fails or required token information is missing.
        """
        resolved_region = region or DEFAULT_REGION
        iam_url = IAM_TEST_URL if staging else IAM_PROD_URL

        self.config = EndpointConfig(
            staging=staging,
            region=resolved_region,
            iam_url=iam_url,
            cos_url=COS_URL_TEMPLATE.format(region=resolved_region),
            code_engine_url=CODE_ENGINE_URL_TEMPLATE.format(region=resolved_region),
        )

        authenticator = IAMAuthenticator(api_key, url=self.config.iam_url)

        # Fetch a token once at init time to validate credentials and extract
        # iam_id / account_id from the JWT payload. Subsequent accesses to
        # auth.token call get_token() directly so the SDK refreshes automatically.
        try:
            initial_token = authenticator.token_manager.get_token()
            decoded = decode_jwt(initial_token)
        except Exception as ex:  # pylint: disable=broad-exception-caught
            logger.warning(
                "IBM Cloud authentication didn't return a valid token: %s.",
                str(ex),
            )
            raise RuntimeError(
                "IBM Cloud authentication didn't return a valid token: " f"{ex}. Verify your token or used endpoints."
            ) from ex

        iam_id = decoded.get("iam_id")
        if iam_id is None:
            raise RuntimeError(
                "Authentication failed: token payload missing 'iam_id'. Verify your token or used endpoints."
            )
        account_data = decoded.get("account")
        if account_data is None:
            raise RuntimeError(
                "Authentication failed: token payload missing 'account'. Verify your token or used endpoints."
            )
        account_id = account_data.get("bss")
        if account_id is None:
            raise RuntimeError(
                "Authentication failed: token payload missing 'account.bss' (account id). "
                "Verify your token or used endpoints."
            )

        self.auth = AuthState(
            authenticator=authenticator,
            iam_id=iam_id,
            account_id=account_id,
            api_key=api_key,
        )
        self.clients = ClientCache()

    def get_cos_hmac_client(
        self,
        *,
        access_key_id: str,
        secret_access_key: str,
        bucket_region: str | None = None,
    ) -> Any:
        """
        Return an S3-compatible IBM COS client using HMAC keys.

        Use for object operations: uploads, downloads, streaming.
        Cached by ``(bucket_region, access_key_id)``.

        Args:
            access_key_id: HMAC access key id from a COS service key.
            secret_access_key: HMAC secret access key from a COS service key.
            bucket_region: Bucket endpoint region. Defaults to the provider default region.

        Returns:
            An S3-compatible ``ibm_boto3`` client configured for IBM COS (HMAC).
        """
        resolved_region = (bucket_region or self.config.region).strip()
        cache_key = (resolved_region, access_key_id)

        cached = self.clients.cos_hmac.get(cache_key)
        if cached is not None:
            return cached

        endpoint_url = COS_URL_TEMPLATE.format(region=resolved_region)
        s3 = ibm_boto3_client(
            "s3",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            endpoint_url=endpoint_url,
            region_name=resolved_region,
        )
        self.clients.cos_hmac[cache_key] = s3
        return s3
