"""Tests for ServiceFunctionalRoleClient. requests and the IAM authenticator are mocked."""

from unittest.mock import MagicMock, patch

import pytest
import requests
from ibm_cloud_sdk_core import ApiException

from core.clients.runtime_api_errors import RuntimeApiError, RuntimeApiRetryableError
from core.clients.service_functional_role_client import ServiceFunctionalRoleClient

FUNCTION_ID = "job-1"
BODY = {"crn": "crn:v1:bluemix:public:quantum-computing:eu-de:a/acct:inst::", "status": "Queued"}


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


def test_sends_one_put_to_the_regional_host_with_a_bearer_token(put):
    ServiceFunctionalRoleClient().put_function(FUNCTION_ID, BODY)

    put.assert_called_once_with(
        "https://eu-de.quantum.test.cloud.ibm.com/api/v1/functions/job-1",
        json=BODY,
        headers={"Authorization": "Bearer iam-token"},
        timeout=3,
    )


def test_the_default_timeout_is_three_seconds_for_both_requests(put, authenticator):
    ServiceFunctionalRoleClient().put_function(FUNCTION_ID, BODY)

    assert put.call_args.kwargs["timeout"] == 3
    assert authenticator.return_value.token_manager.http_config == {"timeout": 3}


def test_the_timeout_argument_bounds_both_requests_on_every_call(put, authenticator):
    client = ServiceFunctionalRoleClient()
    client.put_function(FUNCTION_ID, BODY)

    client.put_function(FUNCTION_ID, BODY, timeout=7)

    assert authenticator.return_value.token_manager.http_config == {"timeout": 7}
    assert put.call_args.kwargs["timeout"] == 7


def test_without_the_key_it_is_a_permanent_error(put, settings):
    settings.FUNCTIONS_OPERATOR_API_KEY = ""

    with pytest.raises(RuntimeApiError) as error:
        ServiceFunctionalRoleClient().put_function(FUNCTION_ID, BODY)

    assert not isinstance(error.value, RuntimeApiRetryableError)
    put.assert_not_called()


def test_202_is_a_success(put):
    put.return_value = MagicMock(status_code=202)

    ServiceFunctionalRoleClient().put_function(FUNCTION_ID, BODY)


@pytest.mark.parametrize("status_code", [400, 404])
def test_a_4xx_status_is_a_permanent_rejection(put, status_code):
    put.return_value = MagicMock(status_code=status_code, text="bad field")

    with pytest.raises(RuntimeApiError) as error:
        ServiceFunctionalRoleClient().put_function(FUNCTION_ID, BODY)

    assert not isinstance(error.value, RuntimeApiRetryableError)
    assert error.value.status_code == status_code


@pytest.mark.parametrize("status_code", [408, 429, 500])
def test_a_transient_status_is_the_retryable_error(put, status_code):
    put.return_value = MagicMock(status_code=status_code, text="try later")

    with pytest.raises(RuntimeApiError) as error:
        ServiceFunctionalRoleClient().put_function(FUNCTION_ID, BODY)

    assert isinstance(error.value, RuntimeApiRetryableError)
    assert error.value.status_code == status_code


def test_an_error_status_logs_the_start_of_the_response_body(put, caplog):
    put.return_value = MagicMock(status_code=400, text="field size is invalid")

    with pytest.raises(RuntimeApiError):
        ServiceFunctionalRoleClient().put_function(FUNCTION_ID, BODY)

    assert "field size is invalid" in caplog.text


def test_network_failures_are_transient(put):
    put.side_effect = requests.ConnectionError("boom")

    with pytest.raises(RuntimeApiError) as error:
        ServiceFunctionalRoleClient().put_function(FUNCTION_ID, BODY)

    assert isinstance(error.value, RuntimeApiRetryableError)


def test_iam_failures_are_transient(put, authenticator):
    authenticator.return_value.token_manager.get_token.side_effect = RuntimeError("iam down")

    with pytest.raises(RuntimeApiError) as error:
        ServiceFunctionalRoleClient().put_function(FUNCTION_ID, BODY)

    assert isinstance(error.value, RuntimeApiRetryableError)
    put.assert_not_called()


def test_an_iam_rejection_of_the_key_is_a_permanent_error(put, authenticator):
    authenticator.return_value.token_manager.get_token.side_effect = ApiException(401, message="unauthorized")

    with pytest.raises(RuntimeApiError) as error:
        ServiceFunctionalRoleClient().put_function(FUNCTION_ID, BODY)

    assert not isinstance(error.value, RuntimeApiRetryableError)
    assert "operator-key" not in str(error.value)
    put.assert_not_called()


def test_a_non_json_iam_response_is_transient(put, authenticator):
    authenticator.return_value.token_manager.get_token.side_effect = requests.exceptions.JSONDecodeError("bad", "", 0)

    with pytest.raises(RuntimeApiError) as error:
        ServiceFunctionalRoleClient().put_function(FUNCTION_ID, BODY)

    assert isinstance(error.value, RuntimeApiRetryableError)


def test_a_malformed_key_is_a_permanent_error(put, authenticator):
    authenticator.side_effect = ValueError("bad key")

    with pytest.raises(RuntimeApiError) as error:
        ServiceFunctionalRoleClient().put_function(FUNCTION_ID, BODY)

    assert not isinstance(error.value, RuntimeApiRetryableError)
    assert "operator-key" not in str(error.value)
    put.assert_not_called()
