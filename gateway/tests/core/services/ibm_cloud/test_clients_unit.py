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
Unit tests for IBMCloudClientProvider and decode_jwt.

- Tokens are generated from readable JSON payloads using base64url encoding.
- All IBM Cloud SDK constructors are patched, so tests never hit the network.
- The "authenticator" used by the provider is replaced by a small fake that only
  implements token_manager.get_token(), which is all the provider needs.
"""

from __future__ import annotations

import base64
import json
from contextlib import contextmanager
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import pytest

from core.ibm_cloud.clients import IBMCloudClientProvider, decode_jwt


def b64url_json(payload: dict[str, Any]) -> str:
    """Convert a JSON-serializable dict into a base64url string without padding."""
    raw = json.dumps(payload).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def make_token(payload: dict[str, Any]) -> str:
    """Create a JWT-like string: header.<base64url(json payload)>.signature."""
    return f"header.{b64url_json(payload)}.signature"


VALID_PAYLOAD: dict[str, Any] = {"iam_id": "iam-123", "account": {"bss": "acct-123"}}
VALID_TOKEN = make_token(VALID_PAYLOAD)


class FakeAuthenticator:  # pylint: disable=too-few-public-methods
    """Minimal authenticator-like object used by IBMCloudClientProvider tests."""

    def __init__(self, token: str) -> None:
        self.token_manager = MagicMock()
        self.token_manager.get_token.return_value = token


@contextmanager
def patched_provider(
    token: str = VALID_TOKEN,
    *,
    token_side_effect: Exception | None = None,
) -> Iterator[IBMCloudClientProvider]:
    """
    Context manager that patches IBM SDK constructors while building a provider.

    Args:
        token: Token returned by IAMAuthenticator().token_manager.get_token().
        token_side_effect: If provided, get_token() raises this.

    Yields:
        IBMCloudClientProvider instance created under patched SDK classes.
    """
    fake_auth = FakeAuthenticator(token)

    if token_side_effect is not None:
        fake_auth.token_manager.get_token.side_effect = token_side_effect

    with (
        patch(
            "core.ibm_cloud.clients.IAMAuthenticator",
            return_value=fake_auth,
        ),
        patch("core.ibm_cloud.clients.ibm_boto3_client") as mock_boto,
    ):
        mock_boto.side_effect = lambda *a, **k: MagicMock()
        yield IBMCloudClientProvider(api_key="dummy-key")


def test_decode_jwt_valid() -> None:
    """decode_jwt should decode a valid token and return expected payload fields."""
    decoded = decode_jwt(VALID_TOKEN)
    assert decoded["iam_id"] == "iam-123"
    assert decoded["account"]["bss"] == "acct-123"


def test_decode_jwt_invalid_format() -> None:
    """decode_jwt should raise on malformed JWT strings."""
    with pytest.raises(Exception):
        decode_jwt("invalid.token")


def test_decode_jwt_invalid_payload() -> None:
    """decode_jwt should raise if the payload is not valid JSON."""
    bad_token = "header.bm90anNvbg.signature"
    with pytest.raises(Exception):
        decode_jwt(bad_token)


def test_provider_token_fetch_exception_bubbles_up() -> None:
    """Provider should bubble up errors from token_manager.get_token()."""
    with pytest.raises(Exception, match="bad key"):
        with patched_provider(token_side_effect=Exception("bad key")):
            pass


def test_provider_decode_jwt_exception_raises_runtimeerror() -> None:
    """Provider should raise RuntimeError if the returned token is not a valid JWT."""
    with pytest.raises(RuntimeError, match="didn't return a valid token"):
        with patched_provider(token="not-a-jwt"):
            pass


def test_provider_extracts_iam_and_account() -> None:
    """Provider should extract iam_id and account_id from the decoded token."""
    with patched_provider() as provider:
        assert provider.auth.iam_id == "iam-123"
        assert provider.auth.account_id == "acct-123"


def test_provider_missing_iam_id() -> None:
    """Provider should raise if iam_id is missing from the token payload."""
    token = make_token({"account": {"bss": "acct-123"}})
    with pytest.raises(RuntimeError):
        with patched_provider(token=token):
            pass


def test_provider_missing_account() -> None:
    """Provider should raise if account data is missing from the token payload."""
    token = make_token({"iam_id": "iam-123"})
    with pytest.raises(RuntimeError):
        with patched_provider(token=token):
            pass


def test_provider_missing_account_id() -> None:
    """Provider should raise if account.bss is missing from the token payload."""
    token = make_token({"iam_id": "iam-123", "account": {}})
    with pytest.raises(RuntimeError):
        with patched_provider(token=token):
            pass


def test_auth_token_delegates_to_sdk() -> None:
    """auth.token should call token_manager.get_token() on every access, not cache the value."""
    with patched_provider() as provider:
        _ = provider.auth.token
        _ = provider.auth.token
        assert provider.auth.authenticator.token_manager.get_token.call_count >= 2


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
        custom_url = "https://s3.private.us-east.cloud-object-storage.appdomain.cloud"
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
        url_private = "https://s3.private.us-east.cloud-object-storage.appdomain.cloud"

        client_pub = provider.get_cos_hmac_client(access_key_id="ak", secret_access_key="sk", endpoint_url=url_public)
        client_priv = provider.get_cos_hmac_client(access_key_id="ak", secret_access_key="sk", endpoint_url=url_private)
        client_pub2 = provider.get_cos_hmac_client(access_key_id="ak", secret_access_key="sk", endpoint_url=url_public)

        assert client_pub is not client_priv
        assert client_pub is client_pub2
