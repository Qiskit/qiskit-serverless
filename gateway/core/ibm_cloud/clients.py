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

Provides :class:`IBMCloudClientProvider`, which resolves the IBM Cloud service endpoints and
creates COS clients. The IAM token comes from a shared :class:`IamTokenProvider`.

Only the minimal surface needed by :class:`FleetsJobHandler` and the COS
layer is included here:

- endpoint resolution, including staging
- COS HMAC S3-compatible client factory

Example::

    from core.ibm_cloud.clients import IBMCloudClientProvider

    provider = IBMCloudClientProvider(api_key="YOUR_API_KEY", region="us-south")

    # HMAC client: uploads/downloads/streaming
    s3 = provider.get_cos_hmac_client(
        access_key_id="ACCESS_KEY",
        secret_access_key="SECRET_KEY",
        bucket_region="us-south",
    )
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ibm_boto3 import client as ibm_boto3_client

from core.clients.iam_token_provider import IamTokenProvider, get_iam_token_provider
from core.ibm_cloud import call_metrics

IAM_PROD_URL = "https://iam.cloud.ibm.com"
IAM_TEST_URL = "https://iam.test.cloud.ibm.com"

COS_URL_TEMPLATE = "https://s3.direct.{region}.cloud-object-storage.appdomain.cloud"
COS_PUBLIC_URL_TEMPLATE = "https://s3.{region}.cloud-object-storage.appdomain.cloud"
CODE_ENGINE_URL_TEMPLATE = "https://api.{region}.codeengine.cloud.ibm.com/v2"

DEFAULT_REGION = "us-south"


@dataclass(frozen=True)
class EndpointConfig:
    """Resolved service endpoints derived from staging mode and region."""

    staging: bool
    region: str
    iam_url: str
    cos_url: str
    code_engine_url: str


@dataclass
class ClientCache:
    """Per-credential COS client cache."""

    # HMAC clients cached by (bucket_region, access_key_id)
    cos_hmac: dict[tuple[str, str], Any] = field(default_factory=dict)


class IBMCloudClientProvider:
    """
    Provider for IBM Cloud SDK clients.

    Resolves the service endpoints and creates COS S3-compatible clients. HMAC clients are created
    on demand and cached for reuse. The IAM token comes from a shared :class:`IamTokenProvider`.

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
            RuntimeApiError: If the API key is empty or malformed. No request is made here, so a
                key IAM rejects surfaces on the first ``tokens.get_token()`` instead.
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

        self.tokens: IamTokenProvider = get_iam_token_provider(api_key, iam_url)
        self.clients = ClientCache()

    def get_cos_hmac_client(
        self,
        *,
        access_key_id: str,
        secret_access_key: str,
        bucket_region: str | None = None,
        endpoint_url: str | None = None,
    ) -> Any:
        """
        Return an S3-compatible IBM COS client using HMAC keys.

        Use for object operations: uploads, downloads, streaming.
        Cached by ``(endpoint_url, access_key_id)``.

        Args:
            access_key_id: HMAC access key id from a COS service key.
            secret_access_key: HMAC secret access key from a COS service key.
            bucket_region: Bucket endpoint region. Defaults to the provider default region.
                Ignored when ``endpoint_url`` is supplied.
            endpoint_url: Override the COS S3 endpoint URL. When set, ``bucket_region``
                is not used to derive the URL (but ``region_name`` is still passed to boto3).

        Returns:
            An S3-compatible ``ibm_boto3`` client configured for IBM COS (HMAC).
        """
        resolved_region = (bucket_region or self.config.region).strip()
        resolved_endpoint = endpoint_url or COS_URL_TEMPLATE.format(region=resolved_region)
        cache_key = (resolved_endpoint, access_key_id)

        cached = self.clients.cos_hmac.get(cache_key)
        if cached is not None:
            return cached

        s3 = ibm_boto3_client(
            "s3",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            endpoint_url=resolved_endpoint,
            region_name=resolved_region,
        )
        s3.meta.events.register("before-call.s3", _start_cos_call)
        s3.meta.events.register("after-call.s3", _end_cos_call)
        s3.meta.events.register("after-call-error.s3", _end_cos_call)
        self.clients.cos_hmac[cache_key] = s3
        return s3


def _start_cos_call(context: dict, **_: Any) -> None:
    context["metrics_start"] = time.monotonic()


def _end_cos_call(context: dict, event_name: str, http_response: Any = None, **_: Any) -> None:
    start = context.pop("metrics_start", None)
    if start is None:
        return
    status = str(http_response.status_code) if http_response is not None else "0"
    call_metrics.observe_cos(event_name.rsplit(".", 1)[-1], status, time.monotonic() - start)
