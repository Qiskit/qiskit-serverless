"""Tests for IamTokenProvider. The IAM authenticator is mocked."""

from unittest.mock import patch

import pytest
import requests
from ibm_cloud_sdk_core import ApiException

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
