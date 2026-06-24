# pylint: disable=import-error, invalid-name, line-too-long, missing-function-docstring, redefined-outer-name
"""Offline unit tests for NtcAdminClient using requests_mock."""

import urllib.parse

import pytest
import requests_mock

from instances.ntc_client import NtcAdminClient, NtcApiError

ACCOUNT_ID = "efb0dd39cdb64955b8f6e32d44290acf"
TOKEN = "ntc-secret-token"
CRN = "crn:v1:staging:public:quantum-computing:us-east:a/efb0dd39cdb64955b8f6e32d44290acf:6f3d655d-796c-43b9-9d03-a765ab3f6f62::"

ADMIN_URL = f"https://quantum.test.cloud.ibm.com/api/v1/accounts/{ACCOUNT_ID}"
RC_URL = f"https://resource-controller.test.cloud.ibm.com/v2/resource_instances/{urllib.parse.quote(CRN, safe='')}"

FUNCTIONS = [
    {
        "name": "instances1-test",
        "provider": "ibm-dev",
        "business_model": "consumption",
        "permissions": ["function.read", "function.run"],
    }
]


@pytest.fixture
def client():
    return NtcAdminClient(account_id=ACCOUNT_ID, token=TOKEN)


def _account_doc():
    return {
        "account_id": f"a/{ACCOUNT_ID}",
        "plans": [
            {
                "plan_id": "53bde9d3-cdbb-46f5-a98f-60ebcadf7260",
                "usage_limit_seconds": 10800,
                "subscription_name": "flex",
                "functions": [
                    {"name": "old", "provider": "ibm", "business_model": "consumption", "permissions": ["x"]}
                ],
                "custom_functions": {"permissions": ["old.write"]},
            },
            {
                "plan_id": "other-plan",
                "usage_limit_seconds": 60,
                "subscription_name": "premium",
                "functions": [
                    {"name": "keep", "provider": "ibm", "business_model": "trial", "permissions": ["keep.read"]}
                ],
            },
        ],
    }


def test_get_account_returns_json_and_uses_lowercase_bearer(client):
    with requests_mock.Mocker() as m:
        m.get(ADMIN_URL, json=_account_doc())
        result = client.get_account()
        assert result["account_id"] == f"a/{ACCOUNT_ID}"
        assert m.last_request.headers["Authorization"] == f"bearer {TOKEN}"


def test_set_account_entitlements_replaces_flex_plan_only(client):
    with requests_mock.Mocker() as m:
        m.get(ADMIN_URL, json=_account_doc())
        m.put(ADMIN_URL, json={}, status_code=200)
        client.set_account_entitlements(FUNCTIONS, ["function-custom.run"])

        body = m.last_request.json()
        assert body["account_id"] == f"a/{ACCOUNT_ID}"
        flex = next(p for p in body["plans"] if p["subscription_name"] == "flex")
        premium = next(p for p in body["plans"] if p["subscription_name"] == "premium")

        assert flex["functions"] == FUNCTIONS
        assert flex["custom_functions"] == {"permissions": ["function-custom.run"]}
        # preserved fields on the flex plan
        assert flex["plan_id"] == "53bde9d3-cdbb-46f5-a98f-60ebcadf7260"
        assert flex["usage_limit_seconds"] == 10800
        # the other plan is untouched
        assert premium["functions"] == [
            {"name": "keep", "provider": "ibm", "business_model": "trial", "permissions": ["keep.read"]}
        ]


def test_set_account_entitlements_none_custom_means_empty(client):
    with requests_mock.Mocker() as m:
        m.get(ADMIN_URL, json=_account_doc())
        m.put(ADMIN_URL, json={}, status_code=200)
        client.set_account_entitlements([], None)
        flex = next(p for p in m.last_request.json()["plans"] if p["subscription_name"] == "flex")
        assert flex["functions"] == []
        assert flex["custom_functions"] == {"permissions": []}


def test_set_account_entitlements_raises_when_plan_missing(client):
    doc = {"account_id": f"a/{ACCOUNT_ID}", "plans": [{"subscription_name": "premium"}]}
    with requests_mock.Mocker() as m:
        m.get(ADMIN_URL, json=doc)
        with pytest.raises(NtcApiError) as exc:
            client.set_account_entitlements(FUNCTIONS, [])
        assert "flex" in str(exc.value)


def test_get_instance_encodes_crn_and_uses_capitalized_bearer(client):
    with requests_mock.Mocker() as m:
        m.get(RC_URL, json={"parameters": {}})
        client.get_instance(CRN)
        assert "%3A" in m.last_request.url  # ':' got percent-encoded
        assert m.last_request.headers["Authorization"] == f"Bearer {TOKEN}"


def test_set_instance_entitlements_preserves_other_parameters(client):
    with requests_mock.Mocker() as m:
        m.get(RC_URL, json={"parameters": {"backends": ["ANY"], "functions": [{"name": "old"}]}})
        m.patch(RC_URL, json={}, status_code=200)
        client.set_instance_entitlements(CRN, FUNCTIONS, ["function-custom.run"])

        params = m.last_request.json()["parameters"]
        assert params["backends"] == ["ANY"]  # preserved
        assert params["functions"] == FUNCTIONS
        assert params["custom_functions"] == {"permissions": ["function-custom.run"]}


def test_set_instance_entitlements_none_custom_leaves_it_untouched(client):
    with requests_mock.Mocker() as m:
        m.get(RC_URL, json={"parameters": {"backends": ["ANY"]}})
        m.patch(RC_URL, json={}, status_code=200)
        client.set_instance_entitlements(CRN, FUNCTIONS, None)
        params = m.last_request.json()["parameters"]
        assert "custom_functions" not in params
        assert params["functions"] == FUNCTIONS


def test_non_2xx_raises_ntc_api_error_with_status_and_body(client):
    with requests_mock.Mocker() as m:
        m.get(ADMIN_URL, status_code=500, text="boom")
        with pytest.raises(NtcApiError) as exc:
            client.get_account()
        assert exc.value.status == 500
        assert exc.value.body == "boom"
