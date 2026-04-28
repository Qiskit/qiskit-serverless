"""Tests for FunctionAccessResult."""

from core.domain.authorization.function_access_entry import FunctionAccessEntry
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import PLATFORM_PERMISSION_RUN, PLATFORM_PERMISSION_READ, PLATFORM_PERMISSION_PROVIDER_JOBS


def _entry(provider_name, function_title, permissions, business_model="SUBSIDIZED"):
    return FunctionAccessEntry(
        provider_name=provider_name,
        function_title=function_title,
        permissions=permissions,
        business_model=business_model,
    )


def test_no_response_get_function_returns_none():
    result = FunctionAccessResult(has_response=False)
    assert result.get_function("p", "f") is None


def test_get_function():
    entry = _entry("prov", "func", {PLATFORM_PERMISSION_RUN})
    result = FunctionAccessResult(has_response=True, functions=[entry])
    assert result.get_function("prov", "func") is entry
    assert result.get_function("other-prov", "func") is None


def test_has_permission_for_provider():
    entries = [
        _entry("prov", "func1", {PLATFORM_PERMISSION_PROVIDER_JOBS}),
        _entry("prov", "func2", {PLATFORM_PERMISSION_READ}),
    ]
    result = FunctionAccessResult(has_response=True, functions=entries)
    assert result.has_permission_for_provider("prov", PLATFORM_PERMISSION_PROVIDER_JOBS) is True
    assert result.has_permission_for_provider("prov", PLATFORM_PERMISSION_PROVIDER_JOBS) is True
    assert result.has_permission_for_provider("prov", PLATFORM_PERMISSION_RUN) is False


def test_get_functions_by_provider():
    entries = [
        _entry("prov-a", "func1", {PLATFORM_PERMISSION_RUN}),
        _entry("prov-a", "func2", {PLATFORM_PERMISSION_RUN}),
        _entry("prov-b", "func3", {PLATFORM_PERMISSION_RUN}),
        _entry("prov-b", "func4", {PLATFORM_PERMISSION_READ}),  # no RUN
    ]
    result = FunctionAccessResult(has_response=True, functions=entries)
    assert result.get_functions_by_provider(PLATFORM_PERMISSION_RUN) == {
        "prov-a": {"func1", "func2"},
        "prov-b": {"func3"},
    }
