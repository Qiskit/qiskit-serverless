"""Tests for FunctionAccessEntry."""

import pytest

from core.domain.authorization.function_access_entry import FunctionAccessEntry
from core.models import PLATFORM_PERMISSION_RUN, PLATFORM_PERMISSION_READ


def test_valid_entry():
    entry = FunctionAccessEntry(
        provider_name="my-provider",
        function_title="my-function",
        permissions={PLATFORM_PERMISSION_RUN, PLATFORM_PERMISSION_READ},
        business_model="TRIAL",
    )
    assert entry.provider_name == "my-provider"
    assert entry.function_title == "my-function"
    assert PLATFORM_PERMISSION_RUN in entry.permissions
    assert entry.business_model == "TRIAL"


def test_business_model_normalized_to_uppercase():
    entry = FunctionAccessEntry(
        provider_name="p",
        function_title="f",
        permissions={PLATFORM_PERMISSION_RUN},
        business_model="trial",
    )
    assert entry.business_model == "TRIAL"


def test_invalid_business_model_raises():
    with pytest.raises(ValueError, match="Invalid business_model"):
        FunctionAccessEntry(
            provider_name="p",
            function_title="f",
            permissions={PLATFORM_PERMISSION_RUN},
            business_model="INVALID",
        )
