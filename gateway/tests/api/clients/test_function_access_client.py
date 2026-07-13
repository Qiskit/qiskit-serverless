"""Tests for FunctionAccessClient — real HTTP server."""

import pytest

from api.clients.function_access_client import FunctionAccessClient
from api.domain.exceptions.runtime_api_exception import RuntimeFunctionsException
from core.config_key import ConfigKey
from core.models import PLATFORM_PERMISSION_RUN, PLATFORM_PERMISSION_CUSTOM_RUN, PLATFORM_PERMISSION_CUSTOM_WRITE


@pytest.fixture(autouse=True)
def _enable_instances_api(monkeypatch):
    monkeypatch.setattr(
        "core.models.Config.get_bool",
        classmethod(lambda cls, key: key == ConfigKey.RUNTIME_INSTANCES_API_ENABLED),
    )


def test_returns_function_from_200_response(instances_server):
    instances_server.grant("ibm", "sampler", [PLATFORM_PERMISSION_RUN])
    instances_server.grant_custom([PLATFORM_PERMISSION_CUSTOM_RUN, PLATFORM_PERMISSION_CUSTOM_WRITE])

    result = FunctionAccessClient().get_accessible_functions("crn:test:123", "test-api-key")

    assert result.use_legacy_authorization is False
    entry = result.get_function("ibm", "sampler")
    assert entry is not None
    assert entry.provider_name == "ibm"
    assert entry.function_title == "sampler"
    assert entry.business_model == "SUBSIDIZED"
    assert PLATFORM_PERMISSION_RUN in entry.permissions

    assert PLATFORM_PERMISSION_CUSTOM_RUN in result.custom_function_permissions
    assert PLATFORM_PERMISSION_CUSTOM_WRITE in result.custom_function_permissions


def test_returns_function_from_200_response_empty(instances_server):
    """When custom_functions.permissions is [], custom_function_permissions is empty."""
    result = FunctionAccessClient().get_accessible_functions("crn:custom:3", "test-api-key")

    assert result.use_legacy_authorization is False
    assert result.custom_function_permissions == set()
    assert result.functions == ()


def test_handles_null_custom_functions(instances_server):
    """custom_functions: null (the cleared shape) must not crash; permissions resolve to empty."""
    instances_server.grant("ibm", "sampler", [PLATFORM_PERMISSION_RUN]).clear_custom()

    result = FunctionAccessClient().get_accessible_functions("crn:null:1", "test-api-key")

    assert result.use_legacy_authorization is False
    assert result.custom_function_permissions == set()
    assert result.get_function("ibm", "sampler") is not None


def test_raises_on_server_error(instances_server):
    instances_server.error(500)

    with pytest.raises(RuntimeFunctionsException):
        FunctionAccessClient().get_accessible_functions("crn:test:789", "test-api-key")


def test_returns_no_response_when_disabled(monkeypatch):
    monkeypatch.setattr("core.models.Config.get_bool", classmethod(lambda cls, key: False))

    result = FunctionAccessClient().get_accessible_functions("crn:test:000", "test-api-key")

    assert result.use_legacy_authorization is True


def test_caches_successful_response(instances_server):
    instances_server.grant("ibm", "sampler", [PLATFORM_PERMISSION_RUN])

    FunctionAccessClient().get_accessible_functions("crn:cache:hit", "test-api-key")
    result = FunctionAccessClient().get_accessible_functions("crn:cache:hit", "test-api-key")

    assert instances_server.request_count == 1
    assert result.use_legacy_authorization is False
    assert result.get_function("ibm", "sampler") is not None


def test_caches_204_response(instances_server):
    instances_server.error(204)

    first = FunctionAccessClient().get_accessible_functions("crn:cache:204", "test-api-key")
    second = FunctionAccessClient().get_accessible_functions("crn:cache:204", "test-api-key")

    assert instances_server.request_count == 1
    assert first.use_legacy_authorization is True
    assert second.use_legacy_authorization is True


def test_does_not_cache_error_response(instances_server):
    instances_server.error(500)

    with pytest.raises(RuntimeFunctionsException):
        FunctionAccessClient().get_accessible_functions("crn:cache:err", "test-api-key")
    with pytest.raises(RuntimeFunctionsException):
        FunctionAccessClient().get_accessible_functions("crn:cache:err", "test-api-key")

    assert instances_server.request_count == 2


# Region routing: the Runtime API is region-scoped. The default region is served by the
# bare host; other regions get a "{region}." host prefix derived from the CRN.

BASE_URL = "https://quantum.cloud.ibm.com"


def _crn(region: str) -> str:
    return f"crn:v1:bluemix:public:quantum-computing:{region}:a/acct:guid::"


def test_regional_url_default_region_unchanged(settings):
    settings.RUNTIME_API_DEFAULT_REGION = "us-east"

    result = FunctionAccessClient()._regional_base_url(BASE_URL, _crn("us-east"))

    assert result == BASE_URL


def test_regional_url_non_default_region_prefixed(settings):
    settings.RUNTIME_API_DEFAULT_REGION = "us-east"

    result = FunctionAccessClient()._regional_base_url(BASE_URL, _crn("eu-de"))

    assert result == "https://eu-de.quantum.cloud.ibm.com"


@pytest.mark.parametrize("crn", ["crn:test:123", "", None])
def test_regional_url_unparseable_crn_falls_back(settings, crn):
    settings.RUNTIME_API_DEFAULT_REGION = "us-east"

    result = FunctionAccessClient()._regional_base_url(BASE_URL, crn)

    assert result == BASE_URL


def test_request_routed_to_region_prefixed_host(settings, requests_mock):
    """End-to-end: a non-default-region CRN sends the /functions request to the
    region-prefixed host, not the bare default-region host."""
    settings.RUNTIME_API_BASE_URL = BASE_URL
    settings.RUNTIME_API_DEFAULT_REGION = "us-east"
    matcher = requests_mock.get("https://eu-de.quantum.cloud.ibm.com/api/v1/functions", status_code=204)

    result = FunctionAccessClient().get_accessible_functions(_crn("eu-de"), "test-api-key")

    assert matcher.called_once
    assert matcher.last_request.headers["Service-CRN"] == _crn("eu-de")
    # 204 → instance not configured in the runtime API, fall back to legacy authorization.
    assert result.use_legacy_authorization is True


def test_request_routed_to_default_host(settings, requests_mock):
    """End-to-end: a default-region CRN uses the bare host with no region prefix."""
    settings.RUNTIME_API_BASE_URL = BASE_URL
    settings.RUNTIME_API_DEFAULT_REGION = "us-east"
    matcher = requests_mock.get("https://quantum.cloud.ibm.com/api/v1/functions", status_code=204)

    FunctionAccessClient().get_accessible_functions(_crn("us-east"), "test-api-key")

    assert matcher.called_once
