"""Tests for WorkloadSender and the per-process client it uses."""

from unittest.mock import patch

import pytest

from core.clients.functions_operator_client import FunctionsOperatorClient, get_functions_operator_client
from core.clients.runtime_api_errors import RuntimeApiError
from core.clients.workload_sender import WorkloadSender

PAYLOAD = {"function_id": "job-1", "body": {"crn": "crn:v1", "status": "Completed"}}


@pytest.fixture(name="client_cache", autouse=True)
def client_cache_fixture():
    get_functions_operator_client.cache_clear()
    yield
    get_functions_operator_client.cache_clear()


def test_sends_the_stored_envelope_with_the_given_timeout():
    with patch("core.clients.workload_sender.get_functions_operator_client") as get_client:
        WorkloadSender().send(PAYLOAD, timeout=2)

    get_client.return_value.put_function.assert_called_once_with("job-1", PAYLOAD["body"], timeout=2)


def test_a_timeout_that_is_not_greater_than_zero_is_refused():
    with patch("core.clients.workload_sender.get_functions_operator_client") as get_client:
        with pytest.raises(ValueError):
            WorkloadSender().send(PAYLOAD, timeout=0)

    get_client.return_value.put_function.assert_not_called()


def test_a_client_error_reaches_the_outbox():
    with patch("core.clients.workload_sender.get_functions_operator_client") as get_client:
        get_client.return_value.put_function.side_effect = RuntimeApiError("rejected")
        with pytest.raises(RuntimeApiError):
            WorkloadSender().send(PAYLOAD)


def test_the_client_is_built_once_per_process_from_the_settings(settings):
    settings.FUNCTIONS_OPERATOR_API_KEY = "operator-key"
    with patch("core.clients.functions_operator_client.IamTokenProvider") as provider:
        assert get_functions_operator_client() is get_functions_operator_client()

    provider.assert_called_once_with("operator-key", settings.IAM_IBM_CLOUD_BASE_URL)
    assert isinstance(get_functions_operator_client(), FunctionsOperatorClient)


def test_a_missing_key_fails_every_call_until_it_is_set(settings):
    settings.FUNCTIONS_OPERATOR_API_KEY = ""
    for _ in range(2):
        with pytest.raises(RuntimeApiError):
            get_functions_operator_client()
