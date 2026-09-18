"""Unit tests for ListFunctionsUseCase."""

import pytest
from django.contrib.auth.models import User

from api.use_cases.programs.list import ListFunctionsUseCase
from core.domain.authorization.function_access_entry import FunctionAccessEntry
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.domain.business_models import BusinessModel
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

    def test_provider_filter_narrows_catalog_to_that_provider(self, user):
        provider_a = Provider.objects.create(name="provider-a")
        provider_b = Provider.objects.create(name="provider-b")
        Program.objects.create(title="fn-a", author=user, provider=provider_a)
        Program.objects.create(title="fn-b", author=user, provider=provider_b)
        accessible = FunctionAccessResult(
            use_legacy_authorization=False,
            functions=[
                FunctionAccessEntry(
                    provider_name="provider-a",
                    function_title="fn-a",
                    business_model=BusinessModel.SUBSIDIZED,
                    permissions={PLATFORM_PERMISSION_READ},
                ),
                FunctionAccessEntry(
                    provider_name="provider-b",
                    function_title="fn-b",
                    business_model=BusinessModel.SUBSIDIZED,
                    permissions={PLATFORM_PERMISSION_READ},
                ),
            ],
        )

        result = ListFunctionsUseCase().execute(user, accessible, "catalog", provider="provider-a")

        assert [f.title for f in result] == ["fn-a"]

    def test_provider_filter_does_not_bypass_permissions(self, user, provider):
        # The function exists under the provider, but the user has no access to it.
        Program.objects.create(title="provider-fn", author=user, provider=provider)
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        result = ListFunctionsUseCase().execute(user, accessible, "catalog", provider="my-provider")

        assert result == []
