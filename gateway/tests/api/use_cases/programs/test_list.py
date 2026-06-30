"""Unit tests for ListFunctionsUseCase."""

import pytest
from django.contrib.auth.models import User

from api.use_cases.programs.list import ListFunctionsUseCase
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


class TestListFunctionsUseCase:
    def test_serverless_filter_returns_only_own_functions(self, user, other_user):
        Program.objects.create(title="my-fn", author=user)
        Program.objects.create(title="other-fn", author=other_user)
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        result = ListFunctionsUseCase().execute(user, accessible, "serverless")

        assert len(result) == 1
        assert result[0].title == "my-fn"

    def test_catalog_filter_returns_provider_functions_with_permission(self, user, provider):
        Program.objects.create(title="provider-fn", author=user, provider=provider)
        accessible = create_function_access_result("my-provider", "provider-fn", {PLATFORM_PERMISSION_READ})

        result = ListFunctionsUseCase().execute(user, accessible, "catalog")

        assert len(result) == 1
        assert result[0].title == "provider-fn"

    def test_catalog_filter_excludes_functions_without_permission(self, user, provider):
        Program.objects.create(title="provider-fn", author=user, provider=provider)
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        result = ListFunctionsUseCase().execute(user, accessible, "catalog")

        assert result == []

    def test_no_filter_returns_own_and_accessible_provider_functions(self, user, provider):
        Program.objects.create(title="my-fn", author=user)
        Program.objects.create(title="provider-fn", author=user, provider=provider)
        accessible = create_function_access_result("my-provider", "provider-fn", {PLATFORM_PERMISSION_READ})

        result = ListFunctionsUseCase().execute(user, accessible, None)

        titles = {f.title for f in result}
        assert "my-fn" in titles
        assert "provider-fn" in titles

    def test_empty_list_when_no_functions_exist(self, user):
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        result = ListFunctionsUseCase().execute(user, accessible, None)

        assert result == []
