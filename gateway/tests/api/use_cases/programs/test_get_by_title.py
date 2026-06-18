"""Unit tests for GetFunctionByTitleUseCase."""

import pytest
from django.contrib.auth.models import User

from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.use_cases.programs.get_by_title import GetFunctionByTitleUseCase
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Program, Provider, PLATFORM_PERMISSION_READ
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


class TestGetFunctionByTitleUseCase:
    def test_finds_own_serverless_function(self, user):
        Program.objects.create(title="my-fn", author=user)
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        result = GetFunctionByTitleUseCase().execute(user, accessible, "my-fn", None)

        assert result.title == "my-fn"

    def test_finds_provider_function_with_permission(self, user, provider):
        Program.objects.create(title="provider-fn", author=user, provider=provider)
        accessible = create_function_access_result("my-provider", "provider-fn", {PLATFORM_PERMISSION_READ})

        result = GetFunctionByTitleUseCase().execute(user, accessible, "provider-fn", "my-provider")

        assert result.title == "provider-fn"

    def test_raises_not_found_when_function_does_not_exist(self, user):
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        with pytest.raises(FunctionNotFoundException):
            GetFunctionByTitleUseCase().execute(user, accessible, "nonexistent", None)

    def test_raises_not_found_when_no_access_to_provider_function(self, user, other_user, provider):
        Program.objects.create(title="provider-fn", author=other_user, provider=provider)
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        with pytest.raises(FunctionNotFoundException):
            GetFunctionByTitleUseCase().execute(user, accessible, "provider-fn", "my-provider")

    def test_raises_not_found_when_provider_function_not_found(self, user, provider):
        accessible = create_function_access_result("my-provider", "ghost-fn", {PLATFORM_PERMISSION_READ})

        with pytest.raises(FunctionNotFoundException):
            GetFunctionByTitleUseCase().execute(user, accessible, "ghost-fn", "my-provider")
