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
from core.clients.runtime_api_errors import RuntimeApiError
from core.domain.exceptions.retryable_error import RetryableError

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

    assert not isinstance(error.value, RetryableError)
    authenticator.assert_not_called()


def test_a_malformed_key_is_a_permanent_error_when_it_is_built(authenticator):
    authenticator.side_effect = ValueError("bad key")

    with pytest.raises(RuntimeApiError) as error:
        IamTokenProvider("operator-key", IAM_URL)

    assert not isinstance(error.value, RetryableError)
    assert "operator-key" not in str(error.value)


def test_an_iam_rejection_of_the_key_is_a_permanent_error(authenticator):
    authenticator.return_value.token_manager.get_token.side_effect = ApiException(401, message="unauthorized")

    with pytest.raises(RuntimeApiError) as error:
        IamTokenProvider("operator-key", IAM_URL).get_token()

    assert not isinstance(error.value, RetryableError)
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

    with pytest.raises(RetryableError):
        IamTokenProvider("operator-key", IAM_URL).get_token()


def _jwt(name="token"):
    now = int(time.time())
    return jwt.encode({"iat": now, "exp": now + 3600, "name": name}, "not-a-real-secret", algorithm="HS256")


def test_a_failed_request_does_not_block_the_next_call(providers):
    """The SDK marks a request as active until it succeeds; without the reset the second call sleeps for 60 s."""
    provider = IamTokenProvider("operator-key", IAM_URL)
    providers.append(provider)
    token = _jwt()
    with patch.object(
        IAMTokenManager,
        "request_token",
        side_effect=[requests.ConnectionError("down"), {"access_token": token, "expires_in": 3600}],
    ) as request_token:
        with pytest.raises(RetryableError):
            provider.get_token()
        started = time.monotonic()
        assert provider.get_token() == token

    assert time.monotonic() - started < 5
    assert request_token.call_count == 2


def test_invalidate_makes_the_next_call_ask_iam_for_a_new_token_but_only_for_the_cached_one(providers):
    provider = IamTokenProvider("operator-key", IAM_URL)
    providers.append(provider)
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


def test_threads_sharing_a_provider_get_the_same_token_with_one_request_to_iam(providers):
    provider = IamTokenProvider("operator-key", IAM_URL)
    providers.append(provider)
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


class _Clock:
    """A fake clock: ``wait`` advances it instead of sleeping, and asks the loop to stop after ``max_waits`` calls."""

    def __init__(self, max_waits=20):
        self.now = 1_000_000.0
        self.waits = []
        self.max_waits = max_waits

    def __call__(self):
        return self.now

    def wait(self, seconds):
        self.waits.append(seconds)
        self.now += seconds
        return len(self.waits) >= self.max_waits


@pytest.fixture(name="providers")
def providers_fixture():
    """Providers built here are closed afterwards, so no refresher thread outlives its test."""
    built = []
    yield built
    for item in built:
        item.close()


def _provider(authenticator, providers, clock, ttl=3600, max_waits=20):
    clock.max_waits = max_waits
    provider = IamTokenProvider("operator-key", IAM_URL, clock=clock, wait=clock.wait)
    providers.append(provider)
    token_manager = authenticator.return_value.token_manager
    token_manager.expire_time = clock.now + ttl
    provider._record_token("first")  # pylint: disable=protected-access
    return provider, token_manager


def _renews_with(token_manager, clock, ttl=3600):
    def renew():
        token_manager.expire_time = clock.now + ttl
        return "renewed"

    token_manager.get_token.side_effect = renew


def test_the_first_token_starts_one_refresher_thread(authenticator, providers):
    token_manager = authenticator.return_value.token_manager
    token_manager.expire_time = time.time() + 3600
    provider = IamTokenProvider("operator-key", IAM_URL)
    providers.append(provider)
    before = threading.active_count()

    provider.get_token()
    provider.get_token()

    assert threading.active_count() == before + 1
    assert provider._thread.daemon  # pylint: disable=protected-access


def test_no_thread_starts_when_the_expiry_is_unknown(authenticator, providers):
    provider = IamTokenProvider("operator-key", IAM_URL)
    providers.append(provider)

    provider.get_token()

    assert provider._thread is None  # pylint: disable=protected-access


def test_it_renews_when_less_than_40_percent_of_the_ttl_is_left(authenticator, providers):
    clock = _Clock()
    provider, token_manager = _provider(authenticator, providers, clock, ttl=3600, max_waits=2)
    _renews_with(token_manager, clock)
    token_manager.refresh_time = 12345

    provider._refresh_loop()  # pylint: disable=protected-access

    # 40% of 3600 s is 1440 s, so the first wait is 3600 - 1440 s and the renewal comes right after it.
    assert clock.waits[0] == 2160
    token_manager.get_token.assert_called_once()
    assert token_manager.refresh_time == 0


def test_a_short_ttl_uses_the_10_minute_floor(authenticator, providers):
    clock = _Clock()
    provider, token_manager = _provider(authenticator, providers, clock, ttl=1200, max_waits=2)
    _renews_with(token_manager, clock, ttl=1200)

    provider._refresh_loop()  # pylint: disable=protected-access

    assert clock.waits[0] == 600


def test_a_failed_renewal_is_retried_every_30_seconds_and_the_thread_survives(authenticator, providers):
    clock = _Clock()
    provider, token_manager = _provider(authenticator, providers, clock, ttl=3600, max_waits=4)

    calls = []

    def renew():
        calls.append(1)
        if len(calls) <= 2:
            raise ApiException(503, message="down")
        token_manager.expire_time = clock.now + 3600
        return "renewed"

    token_manager.get_token.side_effect = renew
    token_manager.request_time = 99

    provider._refresh_loop()  # pylint: disable=protected-access

    assert clock.waits[:3] == [2160, 30, 30]
    assert token_manager.get_token.call_count == 3
    assert token_manager.request_time == 0


def test_an_invalidated_token_is_renewed_at_once(authenticator, providers):
    clock = _Clock()
    provider, token_manager = _provider(authenticator, providers, clock, ttl=3600, max_waits=2)
    _renews_with(token_manager, clock)
    token_manager.access_token = "first"

    provider.invalidate("first")
    provider._refresh_loop()  # pylint: disable=protected-access

    token_manager.get_token.assert_called_once()
    assert clock.waits[0] == 0


def test_a_forked_child_starts_its_own_refresher(authenticator, providers):
    token_manager = authenticator.return_value.token_manager
    token_manager.expire_time = time.time() + 3600
    provider = IamTokenProvider("operator-key", IAM_URL)
    providers.append(provider)
    provider.get_token()
    parent_thread = provider._thread  # pylint: disable=protected-access

    with patch("core.clients.iam_token_provider.os.getpid", return_value=-1):
        provider._ensure_refresher()  # pylint: disable=protected-access

    assert provider._thread is not parent_thread  # pylint: disable=protected-access
    assert provider._thread.is_alive()  # pylint: disable=protected-access


def test_close_stops_the_thread(authenticator):
    token_manager = authenticator.return_value.token_manager
    token_manager.expire_time = time.time() + 3600
    provider = IamTokenProvider("operator-key", IAM_URL)
    provider.get_token()
    thread = provider._thread  # pylint: disable=protected-access

    provider.close()
    thread.join(timeout=5)

    assert not thread.is_alive()


def test_two_providers_have_their_own_threads(authenticator, providers):
    authenticator.return_value.token_manager.expire_time = time.time() + 3600
    first, second = IamTokenProvider("key-one", IAM_URL), IamTokenProvider("key-two", IAM_URL)
    providers.extend([first, second])

    first.get_token()
    second.get_token()

    assert first._thread is not second._thread  # pylint: disable=protected-access
