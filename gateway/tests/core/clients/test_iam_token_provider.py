"""Tests for IamTokenProvider. The IAM authenticator is mocked."""

import threading
import time
from unittest.mock import patch

import jwt
import pytest
import requests
from ibm_cloud_sdk_core import ApiException
from ibm_cloud_sdk_core.token_managers.iam_token_manager import IAMTokenManager

from core.clients.iam_token_provider import IamTokenProvider
from core.clients.runtime_api_errors import RuntimeApiError, RuntimeApiRetryableError

IAM_URL = "https://iam.test.cloud.ibm.com"


@pytest.fixture(name="authenticator")
def authenticator_fixture():
    with patch("core.clients.iam_token_provider.IAMAuthenticator") as authenticator:
        authenticator.return_value.token_manager.get_token.return_value = "iam-token"
        yield authenticator


def test_gives_the_token_and_bounds_the_request_to_iam(authenticator):
    provider = IamTokenProvider("operator-key", IAM_URL)

    assert provider.get_token() == "iam-token"
    authenticator.assert_called_once_with("operator-key", url=IAM_URL)
    assert authenticator.return_value.token_manager.http_config == {"timeout": 3}


def test_the_timeout_is_set_when_it_is_built(authenticator):
    IamTokenProvider("operator-key", IAM_URL, timeout=7)

    assert authenticator.return_value.token_manager.http_config == {"timeout": 7}


def test_an_empty_key_is_a_permanent_error_when_it_is_built(authenticator):
    with pytest.raises(RuntimeApiError) as error:
        IamTokenProvider("", IAM_URL)

    assert not isinstance(error.value, RuntimeApiRetryableError)
    authenticator.assert_not_called()


def test_a_malformed_key_is_a_permanent_error_when_it_is_built(authenticator):
    authenticator.side_effect = ValueError("bad key")

    with pytest.raises(RuntimeApiError) as error:
        IamTokenProvider("operator-key", IAM_URL)

    assert not isinstance(error.value, RuntimeApiRetryableError)
    assert "operator-key" not in str(error.value)


def test_an_iam_rejection_of_the_key_is_a_permanent_error(authenticator):
    authenticator.return_value.token_manager.get_token.side_effect = ApiException(401, message="unauthorized")

    with pytest.raises(RuntimeApiError) as error:
        IamTokenProvider("operator-key", IAM_URL).get_token()

    assert not isinstance(error.value, RuntimeApiRetryableError)
    assert "operator-key" not in str(error.value)


@pytest.mark.parametrize(
    "failure",
    [
        ApiException(503, message="down"),
        RuntimeError("iam down"),
        requests.exceptions.JSONDecodeError("bad", "", 0),
    ],
)
def test_any_other_failure_is_transient(authenticator, failure):
    authenticator.return_value.token_manager.get_token.side_effect = failure

    with pytest.raises(RuntimeApiRetryableError):
        IamTokenProvider("operator-key", IAM_URL).get_token()


def _jwt(name="token"):
    now = int(time.time())
    return jwt.encode({"iat": now, "exp": now + 3600, "name": name}, "not-a-real-secret", algorithm="HS256")


def test_a_failed_request_does_not_block_the_next_call():
    """The SDK marks a request as active until it succeeds; without the reset the second call sleeps for 60 s."""
    provider = IamTokenProvider("operator-key", IAM_URL)
    token = _jwt()
    with patch.object(
        IAMTokenManager,
        "request_token",
        side_effect=[requests.ConnectionError("down"), {"access_token": token, "expires_in": 3600}],
    ) as request_token:
        with pytest.raises(RuntimeApiRetryableError):
            provider.get_token()
        started = time.monotonic()
        assert provider.get_token() == token

    assert time.monotonic() - started < 5
    assert request_token.call_count == 2


def test_invalidate_makes_the_next_call_ask_iam_for_a_new_token_but_only_for_the_cached_one():
    provider = IamTokenProvider("operator-key", IAM_URL)
    first, second = _jwt("first"), _jwt("second")
    with patch.object(
        IAMTokenManager,
        "request_token",
        side_effect=[{"access_token": first, "expires_in": 3600}, {"access_token": second, "expires_in": 3600}],
    ) as request_token:
        assert provider.get_token() == first
        provider.invalidate("some-older-token")
        assert provider.get_token() == first
        provider.invalidate(first)
        assert provider.get_token() == second

    assert request_token.call_count == 2


def test_threads_sharing_a_provider_get_the_same_token_with_one_request_to_iam():
    provider = IamTokenProvider("operator-key", IAM_URL)
    token = _jwt()
    tokens = []
    with patch.object(
        IAMTokenManager, "request_token", return_value={"access_token": token, "expires_in": 3600}
    ) as request_token:
        threads = [threading.Thread(target=lambda: tokens.append(provider.get_token())) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

    assert tokens == [token] * 8
    assert request_token.call_count == 1
