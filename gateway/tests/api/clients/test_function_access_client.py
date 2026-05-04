"""Tests for FunctionAccessClient — real HTTP server."""

import pytest

from api.clients.function_access_client import FunctionAccessClient
from core.config_key import ConfigKey
from core.models import PLATFORM_PERMISSION_RUN


@pytest.fixture(autouse=True)
def _enable_instances_api(monkeypatch):
    monkeypatch.setattr(
        "core.models.Config.get_bool",
        classmethod(lambda cls, key: key == ConfigKey.RUNTIME_INSTANCES_API_ENABLED),
    )


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


def test_returns_no_response_when_disabled(monkeypatch):
    monkeypatch.setattr("core.models.Config.get_bool", classmethod(lambda cls, key: False))

    result = FunctionAccessClient().get_accessible_functions("crn:test:000")

    assert result.has_response is False


def test_caches_successful_response(instances_server):
    instances_server.grant("ibm", "sampler", [PLATFORM_PERMISSION_RUN])

    FunctionAccessClient().get_accessible_functions("crn:cache:hit")
    result = FunctionAccessClient().get_accessible_functions("crn:cache:hit")

    assert instances_server.request_count == 1
    assert result.has_response is True
    assert result.get_function("ibm", "sampler") is not None


def test_does_not_cache_error_response(instances_server):
    instances_server.error(500)

    FunctionAccessClient().get_accessible_functions("crn:cache:err")
    FunctionAccessClient().get_accessible_functions("crn:cache:err")

    assert instances_server.request_count == 2
