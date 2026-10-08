"""Tests for RuntimeApiClient and WorkloadSender. requests and the IAM authenticator are mocked."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from core.clients.runtime_api_client import RuntimeApiClient, RuntimeApiConfigError, RuntimeApiError
from core.clients.workload_sender import WorkloadSender
from core.config_key import ConfigKey

PAYLOAD = {
    "function_id": "job-1",
    "body": {"crn": "crn:v1:bluemix:public:quantum-computing:eu-de:a/acct:inst::", "status": "Queued"},
}


@pytest.fixture(name="flag")
def flag_fixture(monkeypatch):
    state = {"on": True}
    monkeypatch.setattr(
        "core.models.Config.get_bool",
        classmethod(lambda cls, key: state["on"] if key == ConfigKey.WORKLOADS_MIRROR_ENABLED else False),
    )
    return state


@pytest.fixture(name="settings_ready", autouse=True)
def settings_ready_fixture(settings):
    settings.FUNCTIONS_OPERATOR_API_KEY = "operator-key"
    settings.RUNTIME_API_BASE_URL = "https://quantum.test.cloud.ibm.com"
    settings.RUNTIME_API_DEFAULT_REGION = "us-east"
    settings.WORKLOADS_MIRROR_TIMEOUT = 3


@pytest.fixture(name="put")
def put_fixture():
    with (
        patch("core.clients.runtime_api_client.IAMAuthenticator") as authenticator,
        patch("core.clients.runtime_api_client.requests.put") as put,
    ):
        authenticator.return_value.token_manager.get_token.return_value = "iam-token"
        put.return_value = MagicMock(status_code=200)
        yield put


def test_sends_one_put_to_the_regional_host_with_a_bearer_token(flag, put):
    RuntimeApiClient().put_function(PAYLOAD)

    put.assert_called_once_with(
        "https://eu-de.quantum.test.cloud.ibm.com/api/v1/functions/job-1",
        json=PAYLOAD["body"],
        headers={"Authorization": "Bearer iam-token"},
        timeout=3,
    )


def test_flag_off_sends_nothing_and_does_not_need_the_key(flag, put, settings):
    flag["on"] = False
    settings.FUNCTIONS_OPERATOR_API_KEY = ""

    RuntimeApiClient().put_function(PAYLOAD)

    put.assert_not_called()


def test_flag_on_without_the_key_raises_a_config_error(flag, put, settings):
    settings.FUNCTIONS_OPERATOR_API_KEY = ""

    with pytest.raises(RuntimeApiConfigError) as error:
        RuntimeApiClient().put_function(PAYLOAD)

    assert error.value.retryable is False
    put.assert_not_called()


def test_202_is_a_success(flag, put):
    put.return_value = MagicMock(status_code=202)

    RuntimeApiClient().put_function(PAYLOAD)


@pytest.mark.parametrize("status_code, retryable", [(400, False), (404, False), (429, True), (500, True)])
def test_error_status_codes_say_whether_to_retry(flag, put, status_code, retryable):
    put.return_value = MagicMock(status_code=status_code)

    with pytest.raises(RuntimeApiError) as error:
        RuntimeApiClient().put_function(PAYLOAD)

    assert (error.value.status_code, error.value.retryable) == (status_code, retryable)


def test_network_failures_are_retryable(flag, put):
    put.side_effect = requests.ConnectionError("boom")

    with pytest.raises(RuntimeApiError) as error:
        RuntimeApiClient().put_function(PAYLOAD)

    assert error.value.retryable is True


def test_iam_failures_are_retryable(flag, put):
    with patch("core.clients.runtime_api_client.IAMAuthenticator") as authenticator:
        authenticator.return_value.token_manager.get_token.side_effect = RuntimeError("iam down")
        with pytest.raises(RuntimeApiError) as error:
            RuntimeApiClient().put_function(PAYLOAD)

    assert error.value.retryable is True


def test_an_explicit_timeout_reaches_requests(flag, put):
    RuntimeApiClient().put_function(PAYLOAD, timeout=7)

    assert put.call_args.kwargs["timeout"] == 7


def test_the_sender_delegates_to_the_client():
    client = MagicMock()

    WorkloadSender(client).send(PAYLOAD)

    client.put_function.assert_called_once_with(PAYLOAD, timeout=5)


def test_timeout_zero_swallows_a_client_error():
    client = MagicMock()
    client.put_function.side_effect = RuntimeApiError("down", retryable=True)

    WorkloadSender(client).send(PAYLOAD, timeout=0)


def test_a_positive_timeout_lets_the_client_error_raise():
    client = MagicMock()
    client.put_function.side_effect = RuntimeApiError("down", retryable=True)

    with pytest.raises(RuntimeApiError):
        WorkloadSender(client).send(PAYLOAD, timeout=2)
