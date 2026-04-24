"""Tests for FunctionAccessResult."""

from api.domain.authorization.function_access_entry import FunctionAccessEntry
from api.domain.authorization.function_access_result import FunctionAccessResult
from core.models import PLATFORM_ACTION_RUN, PLATFORM_ACTION_VIEW, PLATFORM_ACTION_PROVIDER_JOBS


def _entry(provider_name, function_title, actions, business_model="SUBSIDIZED"):
    return FunctionAccessEntry(
        provider_name=provider_name,
        function_title=function_title,
        actions=actions,
        business_model=business_model,
    )


def test_no_response_get_function_returns_none():
    result = FunctionAccessResult(has_response=False)
    assert result.get_function("p", "f") is None


def test_get_function_found():
    entry = _entry("prov", "func", {PLATFORM_ACTION_RUN})
    result = FunctionAccessResult(has_response=True, functions=[entry])
    assert result.get_function("prov", "func") is entry


def test_get_function_not_found():
    entry = _entry("prov", "func", {PLATFORM_ACTION_RUN})
    result = FunctionAccessResult(has_response=True, functions=[entry])
    assert result.get_function("other-prov", "func") is None


def test_has_action_for_provider_true():
    entries = [
        _entry("prov", "func1", {PLATFORM_ACTION_PROVIDER_JOBS}),
        _entry("prov", "func2", {PLATFORM_ACTION_VIEW}),
    ]
    result = FunctionAccessResult(has_response=True, functions=entries)
    assert result.has_action_for_provider("prov", PLATFORM_ACTION_PROVIDER_JOBS) is True


def test_has_action_for_provider_false():
    entries = [_entry("prov", "func1", {PLATFORM_ACTION_VIEW})]
    result = FunctionAccessResult(has_response=True, functions=entries)
    assert result.has_action_for_provider("prov", PLATFORM_ACTION_PROVIDER_JOBS) is False


def test_get_titles_by_provider():
    entries = [
        _entry("prov-a", "func1", {PLATFORM_ACTION_RUN}),
        _entry("prov-a", "func2", {PLATFORM_ACTION_RUN}),
        _entry("prov-b", "func3", {PLATFORM_ACTION_RUN}),
        _entry("prov-b", "func4", {PLATFORM_ACTION_VIEW}),  # no RUN
    ]
    result = FunctionAccessResult(has_response=True, functions=entries)
    assert result.get_titles_by_provider(PLATFORM_ACTION_RUN) == {
        "prov-a": {"func1", "func2"},
        "prov-b": {"func3"},
    }
