"""Tests for FunctionAccessClient."""

from api.clients.function_access_client import FunctionAccessClient
from core.domain.authorization.function_access_entry import FunctionAccessEntry
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import PLATFORM_PERMISSION_RUN


def test_client_basic_test(monkeypatch):
    entry = FunctionAccessEntry(
        provider_name="my-provider",
        function_title="my-function",
        permissions={PLATFORM_PERMISSION_RUN},
        business_model="SUBSIDIZED",
    )
    expected = FunctionAccessResult(has_response=True, functions=[entry])
    monkeypatch.setattr(FunctionAccessClient, "get_accessible_functions", lambda self, crn: expected)

    result = FunctionAccessClient().get_accessible_functions("crn:123")
    assert result.has_response is True
    assert result.get_function("my-provider", "my-function") is entry
