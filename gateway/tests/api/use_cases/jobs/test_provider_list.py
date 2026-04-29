"""Unit tests for JobsProviderListUseCase."""

import pytest
from django.contrib.auth.models import Group, User

from api.domain.authorization.function_access_entry import FunctionAccessEntry
from api.domain.authorization.function_access_result import FunctionAccessResult
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.domain.exceptions.provider_not_found_exception import ProviderNotFoundException
from api.use_cases.jobs.provider_list import JobsProviderListUseCase
from core.model_managers.jobs import JobFilters
from core.models import Job, PLATFORM_PERMISSION_PROVIDER_JOBS, Program, Provider

pytestmark = pytest.mark.django_db


@pytest.fixture()
def user():
    return User.objects.create_user(username="user")


@pytest.fixture()
def admin_user():
    return User.objects.create_user(username="admin")


@pytest.fixture()
def provider():
    return Provider.objects.create(name="my-provider")


@pytest.fixture()
def provider_with_admin(provider, admin_user):
    g = Group.objects.create(name="my-provider-group")
    admin_user.groups.add(g)
    provider.admin_groups.add(g)
    return provider


@pytest.fixture()
def function(provider, user):
    return Program.objects.create(title="my-function", author=user, provider=provider)


@pytest.fixture()
def jobs(function, user, admin_user):
    j1 = Job.objects.create(author=user, program=function)
    j2 = Job.objects.create(author=admin_user, program=function)
    return [j1, j2]


def _legacy_no_response():
    return FunctionAccessResult(has_response=False)


def _runtime_with_access(provider_name, function_title):
    entry = FunctionAccessEntry(
        provider_name=provider_name,
        function_title=function_title,
        permissions={PLATFORM_PERMISSION_PROVIDER_JOBS},
        business_model=Job.BUSINESS_MODEL_SUBSIDIZED,
    )
    return FunctionAccessResult(has_response=True, functions=[entry])


def _runtime_no_access():
    return FunctionAccessResult(has_response=True, functions=[])


class TestProviderNotFound:
    def test_raises_when_provider_does_not_exist(self, user):
        filters = JobFilters(provider="nonexistent")
        with pytest.raises(ProviderNotFoundException):
            JobsProviderListUseCase().execute(user=user, filters=filters, accessible_functions=_legacy_no_response())


class TestLegacyDjangoGroups:
    def test_admin_can_list_jobs(self, admin_user, provider_with_admin, function, jobs):
        """User in provider admin_groups can list jobs (legacy path)."""
        filters = JobFilters(provider="my-provider")
        result, total = JobsProviderListUseCase().execute(
            user=admin_user, filters=filters, accessible_functions=_legacy_no_response()
        )

        assert total == 2

    def test_non_admin_raises_provider_not_found(self, user, provider_with_admin):
        """User not in admin_groups cannot list jobs (legacy path)."""
        filters = JobFilters(provider="my-provider")
        with pytest.raises(ProviderNotFoundException):
            JobsProviderListUseCase().execute(user=user, filters=filters, accessible_functions=_legacy_no_response())


class TestRuntimeInstances:
    def test_has_access_returns_jobs_filtered_by_function_set(self, user, provider, function, jobs):
        """Runtime path: accessible_functions has the provider/function → jobs filtered by that set."""
        filters = JobFilters(provider="my-provider")
        accessible = _runtime_with_access("my-provider", "my-function")

        result, total = JobsProviderListUseCase().execute(user=user, filters=filters, accessible_functions=accessible)

        assert total == 2

    def test_no_access_raises_provider_not_found(self, user, provider):
        """Runtime path: provider not in accessible_functions → ProviderNotFoundException."""
        filters = JobFilters(provider="my-provider")
        with pytest.raises(ProviderNotFoundException):
            JobsProviderListUseCase().execute(user=user, filters=filters, accessible_functions=_runtime_no_access())

    def test_function_filter_with_access_returns_jobs(self, user, provider, function, jobs):
        """Runtime path + filters.function: can_list_jobs delegated, function exists → jobs returned."""
        filters = JobFilters(provider="my-provider", function="my-function")
        accessible = _runtime_with_access("my-provider", "my-function")

        result, total = JobsProviderListUseCase().execute(user=user, filters=filters, accessible_functions=accessible)

        assert total == 2

    def test_function_filter_denied_raises_provider_not_found(self, user, provider, function):
        """Runtime path + filters.function: can_list_jobs denied → ProviderNotFoundException."""
        filters = JobFilters(provider="my-provider", function="my-function")
        with pytest.raises(ProviderNotFoundException):
            JobsProviderListUseCase().execute(user=user, filters=filters, accessible_functions=_runtime_no_access())

    def test_function_filter_not_in_db_raises_function_not_found(self, user, provider):
        """Runtime path + filters.function: access OK but function not in DB → FunctionNotFoundException."""
        filters = JobFilters(provider="my-provider", function="ghost-function")
        accessible = _runtime_with_access("my-provider", "ghost-function")

        with pytest.raises(FunctionNotFoundException):
            JobsProviderListUseCase().execute(user=user, filters=filters, accessible_functions=accessible)
