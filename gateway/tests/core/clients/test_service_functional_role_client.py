"""Tests for ServiceFunctionalRoleClient and WorkloadSender. requests and the IAM authenticator are mocked."""

from unittest.mock import MagicMock, patch

import pytest
import requests
from ibm_cloud_sdk_core import ApiException

from core.clients.runtime_api_errors import RuntimeApiConfigError, RuntimeApiError
from core.clients.service_functional_role_client import ServiceFunctionalRoleClient
from core.clients.workload_sender import WorkloadSender
from core.config_key import ConfigKey

PAYLOAD = {
    "function_id": "job-1",
    "body": {"crn": "crn:v1:bluemix:public:quantum-computing:eu-de:a/acct:inst::", "status": "Queued"},
}


@pytest.fixture(name="flag")
def flag_fixture(monkeypatch):
    state = {"on": True, "timeout_ms": 3000}
    monkeypatch.setattr(
        "core.models.Config.get_bool",
        classmethod(lambda cls, key: state["on"] if key == ConfigKey.WORKLOADS_MIRROR_ENABLED else False),
    )
    monkeypatch.setattr(
        "core.models.Config.get_int",
        classmethod(
            lambda cls, key, default=0: state["timeout_ms"] if key == ConfigKey.WORKLOADS_MIRROR_TIMEOUT_MS else default
        ),
    )
    return state


@pytest.fixture(name="settings_ready", autouse=True)
def settings_ready_fixture(settings):
    settings.FUNCTIONS_OPERATOR_API_KEY = "operator-key"
    settings.RUNTIME_API_BASE_URL = "https://quantum.test.cloud.ibm.com"
    settings.RUNTIME_API_DEFAULT_REGION = "us-east"


@pytest.fixture(name="authenticator")
def authenticator_fixture():
    with patch("core.clients.service_functional_role_client.IAMAuthenticator") as authenticator:
        authenticator.return_value.token_manager.get_token.return_value = "iam-token"
        yield authenticator


@pytest.fixture(name="put")
def put_fixture(authenticator):  # pylint: disable=unused-argument
    with patch("core.clients.service_functional_role_client.requests.put") as put:
        put.return_value = MagicMock(status_code=200)
        yield put


def test_sends_one_put_to_the_regional_host_with_a_bearer_token(flag, put):
    ServiceFunctionalRoleClient().put_function(PAYLOAD)

    put.assert_called_once_with(
        "https://eu-de.quantum.test.cloud.ibm.com/api/v1/functions/job-1",
        json=PAYLOAD["body"],
        headers={"Authorization": "Bearer iam-token"},
        timeout=3,
    )


def test_the_iam_token_exchange_uses_the_mirror_timeout(flag, put, authenticator):
    ServiceFunctionalRoleClient().put_function(PAYLOAD)

    assert authenticator.return_value.token_manager.http_config == {"timeout": 3}


def test_the_timeout_is_read_on_every_call(flag, put, authenticator):
    client = ServiceFunctionalRoleClient()
    client.put_function(PAYLOAD)

    flag["timeout_ms"] = 7000
    client.put_function(PAYLOAD)

    assert authenticator.return_value.token_manager.http_config == {"timeout": 7}
    assert put.call_args.kwargs["timeout"] == 7


def test_flag_off_sends_nothing_and_does_not_need_the_key(flag, put, authenticator, settings):
    flag["on"] = False
    settings.FUNCTIONS_OPERATOR_API_KEY = ""

    ServiceFunctionalRoleClient().put_function(PAYLOAD)

    put.assert_not_called()
    authenticator.assert_not_called()


def test_flag_on_without_the_key_raises_a_config_error(flag, put, settings):
    settings.FUNCTIONS_OPERATOR_API_KEY = ""

    with pytest.raises(RuntimeApiConfigError) as error:
        ServiceFunctionalRoleClient().put_function(PAYLOAD)

    assert error.value.retryable is False
    put.assert_not_called()


def test_202_is_a_success(flag, put):
    put.return_value = MagicMock(status_code=202)

    ServiceFunctionalRoleClient().put_function(PAYLOAD)


@pytest.mark.parametrize("status_code, retryable", [(400, False), (404, False), (429, True), (500, True)])
def test_error_status_codes_say_whether_to_retry(flag, put, status_code, retryable):
    put.return_value = MagicMock(status_code=status_code, text="bad field")

    with pytest.raises(RuntimeApiError) as error:
        ServiceFunctionalRoleClient().put_function(PAYLOAD)

    assert (error.value.status_code, error.value.retryable) == (status_code, retryable)


def test_an_error_status_logs_the_start_of_the_response_body(flag, put, caplog):
    put.return_value = MagicMock(status_code=400, text="field size is invalid")

    with pytest.raises(RuntimeApiError):
        ServiceFunctionalRoleClient().put_function(PAYLOAD)

    assert "field size is invalid" in caplog.text


def test_network_failures_are_retryable(flag, put):
    put.side_effect = requests.ConnectionError("boom")

    with pytest.raises(RuntimeApiError) as error:
        ServiceFunctionalRoleClient().put_function(PAYLOAD)

    assert error.value.retryable is True


def test_iam_failures_are_retryable(flag, put, authenticator):
    authenticator.return_value.token_manager.get_token.side_effect = RuntimeError("iam down")

    with pytest.raises(RuntimeApiError) as error:
        ServiceFunctionalRoleClient().put_function(PAYLOAD)

    assert error.value.retryable is True
    put.assert_not_called()


def test_an_iam_rejection_of_the_key_is_not_retryable(flag, put, authenticator):
    authenticator.return_value.token_manager.get_token.side_effect = ApiException(401, message="unauthorized")

    with pytest.raises(RuntimeApiConfigError) as error:
        ServiceFunctionalRoleClient().put_function(PAYLOAD)

    assert error.value.retryable is False
    assert "operator-key" not in str(error.value)
    put.assert_not_called()


def test_a_non_json_iam_response_is_retryable(flag, put, authenticator):
    authenticator.return_value.token_manager.get_token.side_effect = requests.exceptions.JSONDecodeError("bad", "", 0)

    with pytest.raises(RuntimeApiError) as error:
        ServiceFunctionalRoleClient().put_function(PAYLOAD)

    assert error.value.retryable is True
    assert not isinstance(error.value, RuntimeApiConfigError)


def test_a_malformed_key_is_not_retryable(flag, put, authenticator):
    authenticator.side_effect = ValueError("bad key")

    with pytest.raises(RuntimeApiConfigError) as error:
        ServiceFunctionalRoleClient().put_function(PAYLOAD)

    assert error.value.retryable is False
    assert "operator-key" not in str(error.value)
    put.assert_not_called()


def test_a_positive_timeout_calls_the_client_synchronously():
    client = MagicMock()

    WorkloadSender(client).send(PAYLOAD)

    client.put_function.assert_called_once_with(PAYLOAD)


def test_timeout_zero_hands_the_call_to_the_best_effort_pool_and_returns():
    client = MagicMock()

    with patch("core.clients.workload_sender.submit_best_effort") as submit:
        WorkloadSender(client).send(PAYLOAD, timeout=0)

    submit.assert_called_once()
    client.put_function.assert_not_called()


@pytest.mark.parametrize("failure", [RuntimeApiError("down", retryable=True), KeyError("body")])
def test_the_submitted_task_swallows_any_client_error(failure):
    client = MagicMock()
    client.put_function.side_effect = failure

    with patch("core.clients.workload_sender.submit_best_effort") as submit:
        WorkloadSender(client).send(PAYLOAD, timeout=0)
    task, *args = submit.call_args.args
    task(*args)

    client.put_function.assert_called_once_with(PAYLOAD)


def test_timeout_zero_never_raises_even_if_the_pool_does():
    with patch("core.clients.workload_sender.submit_best_effort", side_effect=RuntimeError("pool gone")):
        WorkloadSender(MagicMock()).send(PAYLOAD, timeout=0)


def test_a_positive_timeout_lets_the_client_error_raise():
    client = MagicMock()
    client.put_function.side_effect = RuntimeApiError("down", retryable=True)

    with pytest.raises(RuntimeApiError):
        WorkloadSender(client).send(PAYLOAD, timeout=2)
