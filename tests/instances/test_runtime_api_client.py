# pylint: disable=import-error, invalid-name, line-too-long, missing-function-docstring, redefined-outer-name
"""Offline unit tests for RuntimeApiClient using requests_mock.

The response shape mirrors what the gateway parses in
gateway/api/clients/function_access_client.py.
"""

import pytest
import requests_mock

from instances.runtime_api_client import RuntimeApiClient, RuntimeApiError

BASE = "https://quantum.test.cloud.ibm.com"
API_KEY = "user-api-key"
CRN = "crn:v1:staging:public:quantum-computing:us-east:a/acc:inst::"
ENTITLEMENTS_URL = f"{BASE}/api/v1/entitlements"


def envelope(*elements):
    return {"instance_entitlements": list(elements)}


def element(**fields):
    return {"instance_crn": CRN, **fields}


PAYLOAD = envelope(
    element(
        functions=[
            {
                "provider": "ibm-dev",
                "name": "instances1-test",
                "permissions": ["function.read", "function.run", "function.write"],
                "business_model": "consumption",
            },
            {
                "provider": "ibm-dev",
                "name": "instances2-test",
                "permissions": ["function.read"],
                "business_model": "consumption",
            },
        ],
        custom_functions={"permissions": ["function-custom.write", "function-custom.run"]},
    )
)


@pytest.fixture
def client():
    return RuntimeApiClient(BASE, API_KEY)


def test_get_entitlements_sends_service_crn_and_apikey(client):
    with requests_mock.Mocker() as m:
        m.get(ENTITLEMENTS_URL, json=PAYLOAD, status_code=200)
        client.get_entitlements(CRN)
        req = m.last_request
        assert req.headers["Service-CRN"] == CRN
        assert req.headers["Authorization"] == f"apikey {API_KEY}"


def test_get_entitlements_parses_payload(client):
    with requests_mock.Mocker() as m:
        m.get(ENTITLEMENTS_URL, json=PAYLOAD, status_code=200)
        result = client.get_entitlements(CRN)
        assert result.status_code == 200
        assert result.not_configured is False
        assert result.has_function("ibm-dev", "instances1-test")
        assert result.has_function("ibm-dev", "instances2-test")
        assert not result.has_function("ibm-dev", "missing")
        assert result.permissions("ibm-dev", "instances1-test") == {
            "function.read",
            "function.run",
            "function.write",
        }
        assert result.permissions("ibm-dev", "instances2-test") == {"function.read"}
        assert result.permissions("ibm-dev", "missing") == set()
        assert result.custom_permissions == {"function-custom.write", "function-custom.run"}


def test_204_means_not_configured(client):
    with requests_mock.Mocker() as m:
        m.get(ENTITLEMENTS_URL, status_code=204)
        result = client.get_entitlements(CRN)
        assert result.status_code == 204
        assert result.not_configured is True
        assert result.functions == []
        assert result.custom_permissions == set()
        assert not result.has_function("ibm-dev", "instances1-test")


def test_element_granting_nothing_is_configured_but_empty(client):
    with requests_mock.Mocker() as m:
        m.get(ENTITLEMENTS_URL, json=envelope(element()), status_code=200)
        result = client.get_entitlements(CRN)
        assert result.status_code == 200
        assert result.not_configured is False  # 200 with no grants is the clean per-function deny path
        assert result.functions == []
        assert result.custom_permissions == set()


def test_missing_custom_functions_key_is_empty_set(client):
    with requests_mock.Mocker() as m:
        m.get(ENTITLEMENTS_URL, json=envelope(element(functions=[], custom_functions=None)), status_code=200)
        result = client.get_entitlements(CRN)
        assert result.custom_permissions == set()


def test_per_instance_error_raises(client):
    with requests_mock.Mocker() as m:
        payload = envelope(element(error={"code": 1279, "message": f"Instance {CRN} not found."}))
        m.get(ENTITLEMENTS_URL, json=payload, status_code=200)
        with pytest.raises(RuntimeApiError):
            client.get_entitlements(CRN)


def test_no_element_for_the_requested_crn_raises(client):
    with requests_mock.Mocker() as m:
        m.get(ENTITLEMENTS_URL, json=envelope({"instance_crn": "crn:someone:else"}), status_code=200)
        with pytest.raises(RuntimeApiError):
            client.get_entitlements(CRN)


def test_unexpected_status_raises(client):
    with requests_mock.Mocker() as m:
        m.get(ENTITLEMENTS_URL, status_code=500, text="boom")
        with pytest.raises(RuntimeApiError) as exc:
            client.get_entitlements(CRN)
        assert exc.value.status == 500
        assert exc.value.body == "boom"
