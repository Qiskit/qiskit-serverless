"""Tests for FunctionAccessClient."""

import pytest

from api.clients.function_access_client import FunctionAccessClient
from api.domain.authorization.function_access_entry import FunctionAccessEntry
from api.domain.authorization.function_access_result import FunctionAccessResult
from core.models import PLATFORM_ACTION_RUN


def test_base_client_raises_not_implemented():
    client = FunctionAccessClient()
    with pytest.raises(NotImplementedError):
        client.get_accessible_functions("crn:123")


def test_client_can_be_patched_with_data(monkeypatch):
    """In tests, patch get_accessible_functions to return controlled data."""
    entry = FunctionAccessEntry(
        provider_name="my-provider",
        function_title="my-function",
        actions={PLATFORM_ACTION_RUN},
        business_model="SUBSIDIZED",
    )
    expected = FunctionAccessResult(has_response=True, functions=[entry])
    monkeypatch.setattr(FunctionAccessClient, "get_accessible_functions", lambda self, crn: expected)

    result = FunctionAccessClient().get_accessible_functions("crn:123")
    assert result.has_response is True
    assert result.get_function("my-provider", "my-function") is entry
