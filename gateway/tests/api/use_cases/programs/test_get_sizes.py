"""Unit tests for GetFunctionSizesUseCase."""

import pytest
from django.contrib.auth.models import User

from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.use_cases.programs.get_sizes import GetFunctionSizesUseCase
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import ComputeProfile, FunctionSize, Program, Provider, PLATFORM_PERMISSION_READ
from tests.utils import create_function_access_result

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return User.objects.create_user(username="author")


@pytest.fixture
def other_user():
    return User.objects.create_user(username="other")


@pytest.fixture
def provider():
    return Provider.objects.create(name="my-provider")


@pytest.fixture
def profiles():
    small, _ = ComputeProfile.objects.get_or_create(compute_profile_id="4x16")
    large, _ = ComputeProfile.objects.get_or_create(compute_profile_id="8x64")
    return small, large


class TestGetFunctionSizesUseCase:
    def test_returns_catalog_and_default_for_own_function(self, user, profiles):
        small, large = profiles
        function = Program.objects.create(title="my-fn", author=user)
        FunctionSize.objects.create(function=function, function_size="s", compute_profile=small)
        default_row = FunctionSize.objects.create(function=function, function_size="m", compute_profile=large)
        function.default_size = default_row
        function.save(update_fields=["default_size"])
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        sizes, default_size = GetFunctionSizesUseCase().execute(user, accessible, "my-fn", None)

        assert {s.function_size for s in sizes} == {"s", "m"}
        assert default_size == default_row

    def test_returns_empty_catalog_and_no_default_when_none_declared(self, user):
        Program.objects.create(title="bare-fn", author=user)
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        sizes, default_size = GetFunctionSizesUseCase().execute(user, accessible, "bare-fn", None)

        assert sizes == []
        assert default_size is None

    def test_finds_provider_function_with_permission(self, user, provider, profiles):
        small, _ = profiles
        function = Program.objects.create(title="provider-fn", author=user, provider=provider)
        FunctionSize.objects.create(function=function, function_size="s", compute_profile=small)
        accessible = create_function_access_result("my-provider", "provider-fn", {PLATFORM_PERMISSION_READ})

        sizes, _ = GetFunctionSizesUseCase().execute(user, accessible, "provider-fn", "my-provider")

        assert [s.function_size for s in sizes] == ["s"]

    def test_raises_not_found_when_function_does_not_exist(self, user):
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        with pytest.raises(FunctionNotFoundException):
            GetFunctionSizesUseCase().execute(user, accessible, "nonexistent", None)

    def test_raises_not_found_when_no_access_to_provider_function(self, user, other_user, provider):
        Program.objects.create(title="provider-fn", author=other_user, provider=provider)
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        with pytest.raises(FunctionNotFoundException):
            GetFunctionSizesUseCase().execute(user, accessible, "provider-fn", "my-provider")
