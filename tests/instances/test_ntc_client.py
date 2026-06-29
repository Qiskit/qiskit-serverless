# pylint: disable=import-error, invalid-name, line-too-long, missing-function-docstring, redefined-outer-name
"""Offline unit tests for NtcAdminClient using requests_mock."""

import urllib.parse

import pytest
import requests_mock

from instances.ntc_client import NtcAdminClient, NtcApiError

ACCOUNT_ID = "efb0dd39cdb64955b8f6e32d44290acf"
API_KEY = "ntc-api-key"
BEARER = "iam-bearer-token"
CRN = "crn:v1:staging:public:quantum-computing:us-east:a/efb0dd39cdb64955b8f6e32d44290acf:6f3d655d-796c-43b9-9d03-a765ab3f6f62::"

ADMIN_URL = f"https://quantum.test.cloud.ibm.com/api/v1/accounts/{ACCOUNT_ID}"
RC_URL = f"https://resource-controller.test.cloud.ibm.com/v2/resource_instances/{urllib.parse.quote(CRN, safe='')}"
IAM_URL = "https://iam.test.cloud.ibm.com/identity/token"

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
    return NtcAdminClient(account_id=ACCOUNT_ID, api_key=API_KEY)


def _account_doc():
    return {
        "account_id": f"a/{ACCOUNT_ID}",
        "plans": [
            {
                "plan_id": "53bde9d3-cdbb-46f5-a98f-60ebcadf7260",
                "usage_limit_seconds": 10800,
                "subscription_name": "flex",
                "unallocated_usage_seconds": 999,  # server-computed: must be stripped on PUT
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


def test_get_account_returns_json_and_uses_apikey_scheme(client):
    with requests_mock.Mocker() as m:
        m.get(ADMIN_URL, json=_account_doc())
        result = client.get_account()
        assert result["account_id"] == f"a/{ACCOUNT_ID}"
        assert m.last_request.headers["Authorization"] == f"apikey {API_KEY}"


def test_set_account_entitlements_sends_only_target_plan(client):
    with requests_mock.Mocker() as m:
        m.get(ADMIN_URL, json=_account_doc())
        m.put(ADMIN_URL, json={}, status_code=200)
        client.set_account_entitlements(FUNCTIONS, ["function-custom.run"])

        assert m.last_request.headers["Authorization"] == f"apikey {API_KEY}"
        body = m.last_request.json()
        assert body["account_id"] == f"a/{ACCOUNT_ID}"
        # only the target plan (flex) is sent, not the whole plan list (avoids server HTTP 500)
        assert len(body["plans"]) == 1
        flex = body["plans"][0]
        assert flex["subscription_name"] == "flex"
        assert flex["functions"] == FUNCTIONS
        assert flex["custom_functions"] == {"permissions": ["function-custom.run"]}
        # preserved fields on the flex plan
        assert flex["plan_id"] == "53bde9d3-cdbb-46f5-a98f-60ebcadf7260"
        assert flex["usage_limit_seconds"] == 10800
        # server-computed field is stripped
        assert "unallocated_usage_seconds" not in flex


def test_set_account_entitlements_none_custom_clears_with_null(client):
    with requests_mock.Mocker() as m:
        m.get(ADMIN_URL, json=_account_doc())
        m.put(ADMIN_URL, json={}, status_code=200)
        client.set_account_entitlements([], None)
        plans = m.last_request.json()["plans"]
        assert len(plans) == 1
        flex = plans[0]
        assert flex["functions"] == []
        # None clears by nulling the whole field (both [] and {"permissions": null} return HTTP 422)
        assert flex["custom_functions"] is None


def test_set_account_entitlements_empty_list_clears_with_null(client):
    with requests_mock.Mocker() as m:
        m.get(ADMIN_URL, json=_account_doc())
        m.put(ADMIN_URL, json={}, status_code=200)
        client.set_account_entitlements([], [])
        flex = m.last_request.json()["plans"][0]
        assert flex["custom_functions"] is None


def test_set_account_entitlements_preserve_keeps_existing_custom(client):
    with requests_mock.Mocker() as m:
        m.get(ADMIN_URL, json=_account_doc())
        m.put(ADMIN_URL, json={}, status_code=200)
        client.set_account_entitlements(FUNCTIONS)  # custom_permissions defaults to PRESERVE
        flex = m.last_request.json()["plans"][0]
        assert flex["functions"] == FUNCTIONS
        # the field is left untouched: the round-tripped existing value is kept verbatim
        assert flex["custom_functions"] == {"permissions": ["old.write"]}


def test_set_account_entitlements_raises_when_plan_missing(client):
    doc = {"account_id": f"a/{ACCOUNT_ID}", "plans": [{"subscription_name": "premium"}]}
    with requests_mock.Mocker() as m:
        m.get(ADMIN_URL, json=doc)
        with pytest.raises(NtcApiError) as exc:
            client.set_account_entitlements(FUNCTIONS, [])
        assert "flex" in str(exc.value)


def test_get_instance_encodes_crn_and_exchanges_bearer(client):
    with requests_mock.Mocker() as m:
        m.post(IAM_URL, json={"access_token": BEARER})
        m.get(RC_URL, json={"parameters": {}})
        client.get_instance(CRN)
        assert "%3A" in m.request_history[-1].url  # ':' got percent-encoded
        assert m.request_history[-1].headers["Authorization"] == f"Bearer {BEARER}"
        # the IAM token endpoint was called with the api key and apikey grant type
        iam_req = next(r for r in m.request_history if r.url.startswith(IAM_URL))
        assert iam_req.qs["apikey"] == [API_KEY]
        assert iam_req.qs["grant_type"] == ["urn:ibm:params:oauth:grant-type:apikey"]


def test_set_instance_entitlements_preserves_other_parameters(client):
    with requests_mock.Mocker() as m:
        m.post(IAM_URL, json={"access_token": BEARER})
        m.get(RC_URL, json={"parameters": {"backends": ["ANY"], "functions": [{"name": "old"}]}})
        m.patch(RC_URL, json={}, status_code=200)
        client.set_instance_entitlements(CRN, FUNCTIONS, ["function-custom.run"])

        patch_req = m.last_request
        assert patch_req.headers["Authorization"] == f"Bearer {BEARER}"
        params = patch_req.json()["parameters"]
        assert params["backends"] == ["ANY"]  # preserved
        assert params["functions"] == FUNCTIONS
        assert params["custom_functions"] == {"permissions": ["function-custom.run"]}


def test_set_instance_entitlements_preserve_leaves_it_untouched(client):
    with requests_mock.Mocker() as m:
        m.post(IAM_URL, json={"access_token": BEARER})
        m.get(RC_URL, json={"parameters": {"backends": ["ANY"]}})
        m.patch(RC_URL, json={}, status_code=200)
        client.set_instance_entitlements(CRN, FUNCTIONS)  # custom_permissions defaults to PRESERVE
        params = m.last_request.json()["parameters"]
        assert "custom_functions" not in params
        assert params["functions"] == FUNCTIONS


def test_set_instance_entitlements_none_custom_clears_with_null(client):
    with requests_mock.Mocker() as m:
        m.post(IAM_URL, json={"access_token": BEARER})
        m.get(RC_URL, json={"parameters": {"backends": ["ANY"]}})
        m.patch(RC_URL, json={}, status_code=200)
        client.set_instance_entitlements(CRN, FUNCTIONS, None)
        params = m.last_request.json()["parameters"]
        # None clears by nulling the whole field (both [] and {"permissions": null} return HTTP 422)
        assert params["custom_functions"] is None
        assert params["functions"] == FUNCTIONS


def test_set_instance_entitlements_sends_advancing_timestamp(client):
    # The instance already carries a timestamp in the FUTURE (as if the server narrow-sync stamped it
    # with a clock ahead of ours). The PATCH must send a timestamp strictly greater than it, both at
    # the top level and inside parameters, so a re-add wins the last-write-wins comparison.
    existing = "2099-01-01T00:00:00.123456789Z"
    with requests_mock.Mocker() as m:
        m.post(IAM_URL, json={"access_token": BEARER})
        m.get(RC_URL, json={"parameters": {"timestamp": existing}})
        m.patch(RC_URL, json={}, status_code=200)
        client.set_instance_entitlements(CRN, FUNCTIONS, [])

        body = m.last_request.json()
        assert body["timestamp"] > existing
        assert body["parameters"]["timestamp"] == body["timestamp"]


def test_iam_bearer_is_cached_across_instance_calls(client):
    with requests_mock.Mocker() as m:
        m.post(IAM_URL, json={"access_token": BEARER})
        m.get(RC_URL, json={"parameters": {}})
        client.get_instance(CRN)
        client.get_instance(CRN)
        iam_calls = [r for r in m.request_history if r.url.startswith(IAM_URL)]
        assert len(iam_calls) == 1  # exchanged once, then cached


def test_non_2xx_raises_ntc_api_error_with_status_and_body(client):
    with requests_mock.Mocker() as m:
        m.get(ADMIN_URL, status_code=500, text="boom")
        with pytest.raises(NtcApiError) as exc:
            client.get_account()
        assert exc.value.status == 500
        assert exc.value.body == "boom"


def test_rc_api_key_used_for_iam_only_account_uses_api_key():
    rc_api_key = "rc-only-key"
    client = NtcAdminClient(account_id=ACCOUNT_ID, api_key=API_KEY, rc_api_key=rc_api_key)
    with requests_mock.Mocker() as m:
        m.post(IAM_URL, json={"access_token": BEARER})
        m.get(ADMIN_URL, json={"account_id": f"a/{ACCOUNT_ID}", "plans": []})
        m.get(RC_URL, json={"parameters": {}})

        client.get_account()  # account admin path -> apikey API_KEY
        client.get_instance(CRN)  # instance path -> IAM exchange with rc_api_key, then Bearer

        acct_req = next(r for r in m.request_history if r.url.startswith(ADMIN_URL))
        assert acct_req.headers["Authorization"] == f"apikey {API_KEY}"

        iam_req = next(r for r in m.request_history if r.url.startswith(IAM_URL))
        assert iam_req.qs["apikey"] == [rc_api_key]

        rc_req = next(r for r in m.request_history if r.url.startswith(RC_URL))
        assert rc_req.headers["Authorization"] == f"Bearer {BEARER}"
