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
Unit tests for IBMCloudClientProvider and the shared IAM token provider factory.

The IAM token itself is IamTokenProvider's job and is tested in
tests/core/clients/test_iam_token_provider.py. Here the provider is given a fake one, so these
tests never hit the network and only cover what this module owns: the endpoint config, the COS
HMAC client cache, and that one token provider is shared per credentials.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest
from urllib3.exceptions import ReadTimeoutError

from core.ibm_cloud import get_ce_auth
from core.ibm_cloud.clients import IBMCloudClientProvider
from core.clients.iam_token_provider import get_iam_token_provider


class FakeTokenProvider:  # pylint: disable=too-few-public-methods
    """Stands in for IamTokenProvider: all the client provider needs is get_token()."""

    def __init__(self, *tokens: str) -> None:
        self.get_token = MagicMock(side_effect=list(tokens) or ["a-token"])


@contextmanager
def patched_provider(tokens: FakeTokenProvider | None = None) -> Iterator[IBMCloudClientProvider]:
    """Build a provider with a fake token provider and no real boto3 client."""
    with (
        patch("core.ibm_cloud.clients.get_iam_token_provider", return_value=tokens or FakeTokenProvider()),
        patch("core.ibm_cloud.clients.ibm_boto3_client") as mock_boto,
    ):
        mock_boto.side_effect = lambda *a, **k: MagicMock()
        yield IBMCloudClientProvider(api_key="dummy-key")


def test_get_cos_hmac_client_cache_hit_and_miss() -> None:
    """get_cos_hmac_client should cache per (region, credentials) and return new clients for new creds."""
    with patched_provider() as provider:
        cos1 = provider.get_cos_hmac_client(
            access_key_id="ak",
            secret_access_key="sk",
            bucket_region="us-east",
        )
        cos2 = provider.get_cos_hmac_client(
            access_key_id="ak",
            secret_access_key="sk",
            bucket_region="us-east",
        )
        cos3 = provider.get_cos_hmac_client(
            access_key_id="ak2",
            secret_access_key="sk2",
            bucket_region="us-east",
        )

        assert cos1 is cos2
        assert cos1 is not cos3


def test_get_cos_hmac_client_uses_custom_endpoint_url() -> None:
    """When endpoint_url is supplied it is used as the S3 endpoint, not the region-derived URL."""
    with patched_provider() as provider:
        custom_url = "https://s3.direct.us-east.cloud-object-storage.appdomain.cloud"
        provider.get_cos_hmac_client(
            access_key_id="ak",
            secret_access_key="sk",
            endpoint_url=custom_url,
        )
        assert (custom_url, "ak") in provider.clients.cos_hmac


def test_get_cos_hmac_client_cache_differentiates_by_endpoint_url() -> None:
    """Different endpoint URLs for the same credentials produce distinct cached clients."""
    with patched_provider() as provider:
        url_public = "https://s3.us-east.cloud-object-storage.appdomain.cloud"
        url_direct = "https://s3.direct.us-east.cloud-object-storage.appdomain.cloud"

        client_pub = provider.get_cos_hmac_client(access_key_id="ak", secret_access_key="sk", endpoint_url=url_public)
        client_direct = provider.get_cos_hmac_client(
            access_key_id="ak", secret_access_key="sk", endpoint_url=url_direct
        )
        client_pub2 = provider.get_cos_hmac_client(access_key_id="ak", secret_access_key="sk", endpoint_url=url_public)

        assert client_pub is not client_direct
        assert client_pub is client_pub2


def test_providers_with_the_same_credentials_share_one_token_provider() -> None:
    """The SDK caches the token on the provider, so a second one would discard that cache."""
    with patch("core.clients.iam_token_provider.IamTokenProvider") as mock_cls:
        first = get_iam_token_provider("key-a", "https://iam.example")
        second = get_iam_token_provider("key-a", "https://iam.example")

    assert mock_cls.call_count == 1
    assert first is second


def test_a_different_api_key_gets_its_own_token_provider() -> None:
    """The cache key includes the api key, so one key's token never serves another."""
    with patch("core.clients.iam_token_provider.IamTokenProvider") as mock_cls:
        get_iam_token_provider("key-a", "https://iam.example")
        get_iam_token_provider("key-b", "https://iam.example")

    assert mock_cls.call_count == 2


def test_the_code_engine_client_re_reads_the_token_before_a_request() -> None:
    """The generated client calls refresh_api_key_hook from get_api_key_with_prefix, so the token a
    kept client sends is read per request and not the snapshot taken when it was built."""
    tokens = FakeTokenProvider("fresh-token")
    with (
        patch("core.ibm_cloud.clients.get_iam_token_provider", return_value=tokens),
        patch("core.ibm_cloud.clients.ibm_boto3_client"),
    ):
        ce_auth = get_ce_auth("dummy-key", "us-east")

    cfg = ce_auth.api_client.configuration
    assert cfg.api_key == {}  # nothing is read at build time
    assert cfg.get_api_key_with_prefix("Authorization") == "Bearer fresh-token"


def test_a_code_engine_client_without_read_retries_raises_a_timed_out_read_at_once() -> None:
    with (
        patch("core.ibm_cloud.clients.get_iam_token_provider"),
        patch("core.ibm_cloud.clients.ibm_boto3_client"),
    ):
        ce_auth = get_ce_auth("dummy-key", "us-east", retry_reads=False)

    retries = ce_auth.api_client.rest_client.pool_manager.connection_pool_kw["retries"]
    with pytest.raises(ReadTimeoutError):
        retries.increment(method="GET", url="/", error=ReadTimeoutError(None, "/", "read timed out"))
    assert not retries.is_retry("GET", 429, has_retry_after=True)
