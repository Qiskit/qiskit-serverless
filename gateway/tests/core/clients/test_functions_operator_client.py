"""Tests for FunctionsOperatorClient. requests is mocked and the token provider is a stand-in."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from core.clients.runtime_api_errors import RuntimeApiError, RuntimeApiRetryableError
from core.clients.functions_operator_client import FunctionsOperatorClient

FUNCTION_ID = "job-1"
BODY = {"crn": "crn:v1:bluemix:public:quantum-computing:eu-de:a/acct:inst::", "status": "Queued"}


@pytest.fixture(name="settings_ready", autouse=True)
def settings_ready_fixture(settings):
    settings.RUNTIME_API_BASE_URL = "https://quantum.test.cloud.ibm.com"
    settings.RUNTIME_API_DEFAULT_REGION = "us-east"


@pytest.fixture(name="token_provider")
def token_provider_fixture():
    provider = MagicMock()
    provider.get_token.return_value = "iam-token"
    return provider


@pytest.fixture(name="client")
def client_fixture(token_provider):
    return FunctionsOperatorClient(token_provider)


@pytest.fixture(name="put")
def put_fixture():
    with patch("core.clients.functions_operator_client.requests.put") as put:
        put.return_value = MagicMock(status_code=200)
        yield put


def test_sends_one_put_to_the_regional_host_with_a_bearer_token(client, put):
    client.put_function(FUNCTION_ID, BODY)

    put.assert_called_once_with(
        "https://eu-de.quantum.test.cloud.ibm.com/api/v1/functions/job-1",
        json=BODY,
        headers={"Authorization": "Bearer iam-token"},
        timeout=3,
    )


def test_the_timeout_argument_bounds_the_put(client, put):
    client.put_function(FUNCTION_ID, BODY, timeout=7)

    assert put.call_args.kwargs["timeout"] == 7


def test_a_token_error_is_raised_as_it_is_and_nothing_is_sent(client, token_provider, put):
    token_provider.get_token.side_effect = RuntimeApiRetryableError("Could not get an IAM token")

    with pytest.raises(RuntimeApiRetryableError):
        client.put_function(FUNCTION_ID, BODY)

    put.assert_not_called()


def test_202_is_a_success(client, put):
    put.return_value = MagicMock(status_code=202)

    client.put_function(FUNCTION_ID, BODY)


@pytest.mark.parametrize("status_code", [400, 404])
def test_a_4xx_status_is_a_permanent_rejection(client, put, status_code):
    put.return_value = MagicMock(status_code=status_code, text="bad field")

    with pytest.raises(RuntimeApiError) as error:
        client.put_function(FUNCTION_ID, BODY)

    assert not isinstance(error.value, RuntimeApiRetryableError)
    assert error.value.status_code == status_code


@pytest.mark.parametrize("status_code", [401, 403, 408, 429, 500])
def test_a_transient_status_is_the_retryable_error(client, put, status_code):
    put.return_value = MagicMock(status_code=status_code, text="try later")

    with pytest.raises(RuntimeApiError) as error:
        client.put_function(FUNCTION_ID, BODY)

    assert isinstance(error.value, RuntimeApiRetryableError)
    assert error.value.status_code == status_code


def test_an_error_status_logs_the_start_of_the_response_body(client, put, caplog):
    put.return_value = MagicMock(status_code=400, text="field size is invalid")

    with pytest.raises(RuntimeApiError):
        client.put_function(FUNCTION_ID, BODY)

    assert "field size is invalid" in caplog.text


def test_network_failures_are_transient(client, put):
    put.side_effect = requests.ConnectionError("boom")

    with pytest.raises(RuntimeApiRetryableError):
        client.put_function(FUNCTION_ID, BODY)


@pytest.mark.parametrize("crn", [None, ""])
def test_a_body_without_crn_is_a_permanent_error_and_nothing_is_sent(client, token_provider, put, crn):
    with pytest.raises(RuntimeApiError) as error:
        client.put_function(FUNCTION_ID, {**BODY, "crn": crn})

    assert not isinstance(error.value, RuntimeApiRetryableError)
    token_provider.get_token.assert_not_called()
    put.assert_not_called()


def test_the_token_never_reaches_the_logs_or_the_error(client, put, caplog):
    put.return_value = MagicMock(status_code=500, text="boom")

    with pytest.raises(RuntimeApiRetryableError) as error:
        client.put_function(FUNCTION_ID, BODY)

    assert "iam-token" not in caplog.text
    assert "iam-token" not in str(error.value)
