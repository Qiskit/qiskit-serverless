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
import os
import uuid as uuid_module
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import pytest

from core.ibm_cloud.clients import IBMCloudClientProvider, IBMEventStreamsClient, decode_jwt


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


_CLIENT_MOD = "core.ibm_cloud.clients"


def _make_job(
    job_id=None,
    instance_crn="crn:v1:bluemix:public:quantum-computing:us-east:a/abc:def::",
    running_started_at=None,
):
    job = MagicMock()
    job.id = job_id or uuid_module.uuid4()
    job.instance_crn = instance_crn
    job.running_started_at = running_started_at or datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return job


class TestIBMEventStreamsClient:
    def test_producer_configured_with_sasl_plain_tls(self):
        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
            with patch.dict(
                os.environ,
                {
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS": "broker1:9093",
                    "EVENT_STREAMS_API_KEY": "my-key",
                    "ENVIRONMENT": "staging",
                },
            ):
                IBMEventStreamsClient()

        mock_producer_cls.assert_called_once_with({
            "bootstrap.servers": "broker1:9093",
            "security.protocol": "SASL_SSL",
            "sasl.mechanisms": "PLAIN",
            "sasl.username": "token",
            "sasl.password": "my-key",
        })

    def test_topic_constructed_from_environment(self):
        with patch(f"{_CLIENT_MOD}.Producer"):
            with patch.dict(os.environ, {
                "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                "EVENT_STREAMS_API_KEY": "k",
                "ENVIRONMENT": "staging",
            }):
                client = IBMEventStreamsClient()

        assert client.topic == "quantum.staging.function-usage.v1"

    def test_emit_job_started_publishes_correct_payload(self):
        job = _make_job()

        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
            with patch(f"{_CLIENT_MOD}.uuid") as mock_uuid_mod:
                with patch(f"{_CLIENT_MOD}.datetime") as mock_dt:
                    with patch.dict(os.environ, {
                        "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                        "EVENT_STREAMS_API_KEY": "k",
                        "ENVIRONMENT": "production",
                    }):
                        fake_event_id = uuid_module.UUID("00000000-0000-0000-0000-000000000001")
                        mock_uuid_mod.uuid4.return_value = fake_event_id
                        fake_now = datetime(2026, 1, 1, 12, 0, 1, tzinfo=timezone.utc)
                        mock_dt.now.return_value = fake_now

                        client = IBMEventStreamsClient()
                        mock_producer = mock_producer_cls.return_value
                        mock_producer.flush.return_value = 0
                        client.emit_job_started(job)

        import json
        published = json.loads(mock_producer.produce.call_args[1]["value"])
        assert published["specversion"] == "1.0"
        assert published["type"] == "quantum.production.function-usage.v1"
        assert published["source"] == "qiskit-serverless/scheduler/fleets"
        assert published["subject"] == str(job.id)
        assert published["data"]["event_type"] == "job_started"
        assert published["data"]["usage_nanoseconds"] == 0
        assert published["data"]["instance_crn"] == job.instance_crn
        mock_producer.flush.assert_called_once()

    def test_emit_job_in_progress_computes_usage_nanoseconds(self):
        started_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        job = _make_job(running_started_at=started_at)

        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
            with patch(f"{_CLIENT_MOD}.uuid") as mock_uuid_mod:
                with patch(f"{_CLIENT_MOD}.datetime") as mock_dt:
                    with patch.dict(os.environ, {
                        "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                        "EVENT_STREAMS_API_KEY": "k",
                        "ENVIRONMENT": "production",
                    }):
                        mock_uuid_mod.uuid4.return_value = uuid_module.uuid4()
                        mock_dt.now.return_value = datetime(2026, 1, 1, 12, 0, 5, tzinfo=timezone.utc)

                        client = IBMEventStreamsClient()
                        mock_producer = mock_producer_cls.return_value
                        mock_producer.flush.return_value = 0
                        client.emit_job_in_progress(job)

        import json
        published = json.loads(mock_producer.produce.call_args[1]["value"])
        assert published["data"]["event_type"] == "job_in_progress"
        assert published["data"]["usage_nanoseconds"] == 5_000_000_000

    def test_emit_job_ended_computes_usage_nanoseconds(self):
        started_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        job = _make_job(running_started_at=started_at)

        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
            with patch(f"{_CLIENT_MOD}.uuid") as mock_uuid_mod:
                with patch(f"{_CLIENT_MOD}.datetime") as mock_dt:
                    with patch.dict(os.environ, {
                        "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                        "EVENT_STREAMS_API_KEY": "k",
                        "ENVIRONMENT": "production",
                    }):
                        mock_uuid_mod.uuid4.return_value = uuid_module.uuid4()
                        mock_dt.now.return_value = datetime(2026, 1, 1, 12, 0, 30, tzinfo=timezone.utc)

                        client = IBMEventStreamsClient()
                        mock_producer = mock_producer_cls.return_value
                        mock_producer.flush.return_value = 0
                        client.emit_job_ended(job)

        import json
        published = json.loads(mock_producer.produce.call_args[1]["value"])
        assert published["data"]["event_type"] == "job_ended"
        assert published["data"]["usage_nanoseconds"] == 30_000_000_000

    def test_emit_job_in_progress_returns_zero_usage_when_running_started_at_is_none(self):
        job = _make_job(running_started_at=None)
        job.running_started_at = None  # override the default

        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
            with patch(f"{_CLIENT_MOD}.uuid") as mock_uuid_mod:
                with patch(f"{_CLIENT_MOD}.datetime") as mock_dt:
                    with patch.dict(os.environ, {
                        "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                        "EVENT_STREAMS_API_KEY": "k",
                        "ENVIRONMENT": "production",
                    }):
                        mock_uuid_mod.uuid4.return_value = uuid_module.uuid4()
                        mock_dt.now.return_value = datetime(2026, 1, 1, 12, 0, 5, tzinfo=timezone.utc)

                        client = IBMEventStreamsClient()
                        mock_producer = mock_producer_cls.return_value
                        mock_producer.flush.return_value = 0
                        client.emit_job_in_progress(job)

        import json
        published = json.loads(mock_producer.produce.call_args[1]["value"])
        assert published["data"]["usage_nanoseconds"] == 0
