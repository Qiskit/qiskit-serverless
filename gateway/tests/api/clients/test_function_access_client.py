"""Tests for FunctionAccessClient — real HTTP server."""

from api.clients.function_access_client import FunctionAccessClient
from core.models import PLATFORM_PERMISSION_RUN


def test_returns_function_from_200_response(instances_server):
    instances_server.grant("ibm", "sampler", [PLATFORM_PERMISSION_RUN])

    result = FunctionAccessClient().get_accessible_functions("crn:test:123")

    assert result.has_response is True
    entry = result.get_function("ibm", "sampler")
    assert entry is not None
    assert entry.provider_name == "ibm"
    assert entry.function_title == "sampler"
    assert entry.business_model == "SUBSIDIZED"
    assert PLATFORM_PERMISSION_RUN in entry.permissions


def test_returns_empty_list_on_200_with_no_functions(instances_server):
    instances_server.reset()

    result = FunctionAccessClient().get_accessible_functions("crn:test:456")

    assert result.has_response is True
    assert result.functions == []


def test_returns_no_response_on_server_error(instances_server):
    instances_server.error(500)

    result = FunctionAccessClient().get_accessible_functions("crn:test:789")

    assert result.has_response is False


def test_returns_no_response_when_url_not_configured(settings):
    settings.RUNTIME_INSTANCES_API_BASE_URL = ""

    result = FunctionAccessClient().get_accessible_functions("crn:test:000")

    assert result.has_response is False
