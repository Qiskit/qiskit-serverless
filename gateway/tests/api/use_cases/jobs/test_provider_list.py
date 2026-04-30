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


def _no_response():
    return FunctionAccessResult(has_response=False)


def create_function_access_result(provider_name, function_title, permissions):
    entry = FunctionAccessEntry(
        provider_name=provider_name,
        function_title=function_title,
        permissions=permissions,
        business_model=Job.BUSINESS_MODEL_SUBSIDIZED,
    )
    return FunctionAccessResult(has_response=True, functions=[entry])


class TestProviderNotFound:
    def test_raises_when_provider_does_not_exist(self, user):
        filters = JobFilters(provider="nonexistent")
        with pytest.raises(ProviderNotFoundException):
            JobsProviderListUseCase().execute(user=user, filters=filters, accessible_functions=_no_response())


class TestListJobs:
    class TestLegacyGroups:
        def test_admin_can_list_all_jobs(self, admin_user, provider_with_admin, function, jobs):
            """User in provider admin_groups can list all jobs."""
            filters = JobFilters(provider="my-provider")
            _, total = JobsProviderListUseCase().execute(
                user=admin_user, filters=filters, accessible_functions=_no_response()
            )
            assert total == 2

        def test_non_admin_raises_provider_not_found(self, user, provider_with_admin):
            """User not in admin_groups cannot list jobs."""
            filters = JobFilters(provider="my-provider")
            with pytest.raises(ProviderNotFoundException):
                JobsProviderListUseCase().execute(user=user, filters=filters, accessible_functions=_no_response())

        def test_admin_with_function_filter_returns_jobs(self, admin_user, provider_with_admin, function, jobs):
            """Admin can filter by a specific function title."""
            filters = JobFilters(provider="my-provider", function="my-function")
            _, total = JobsProviderListUseCase().execute(
                user=admin_user, filters=filters, accessible_functions=_no_response()
            )
            assert total == 2

        def test_non_admin_with_function_filter_raises(self, user, provider_with_admin, function):
            """Non-admin cannot filter by function title."""
            filters = JobFilters(provider="my-provider", function="my-function")
            with pytest.raises(ProviderNotFoundException):
                JobsProviderListUseCase().execute(user=user, filters=filters, accessible_functions=_no_response())

    class TestRuntimeInstances:
        @pytest.mark.parametrize(
            "permissions,expected_total",
            [
                ({PLATFORM_PERMISSION_PROVIDER_JOBS}, 2),
                ({"other-permission"}, None),
            ],
        )
        def test_access_depends_on_provider_jobs_permission(
            self, user, provider, function, jobs, permissions, expected_total
        ):
            """Jobs returned or ProviderNotFoundException depending on PLATFORM_PERMISSION_PROVIDER_JOBS."""
            filters = JobFilters(provider="my-provider")
            accessible = create_function_access_result("my-provider", "my-function", permissions)
            if expected_total is None:
                with pytest.raises(ProviderNotFoundException):
                    JobsProviderListUseCase().execute(user=user, filters=filters, accessible_functions=accessible)
            else:
                _, total = JobsProviderListUseCase().execute(
                    user=user, filters=filters, accessible_functions=accessible
                )
                assert total == expected_total

        def test_no_entries_raises_provider_not_found(self, user, provider):
            """Runtime path with no entries at all → ProviderNotFoundException."""
            filters = JobFilters(provider="my-provider")
            with pytest.raises(ProviderNotFoundException):
                JobsProviderListUseCase().execute(
                    user=user,
                    filters=filters,
                    accessible_functions=FunctionAccessResult(has_response=True, functions=[]),
                )

        def test_function_filter_with_access_returns_jobs(self, user, provider, function, jobs):
            """Function filter with access → jobs for that function returned."""
            filters = JobFilters(provider="my-provider", function="my-function")
            accessible = create_function_access_result(
                "my-provider", "my-function", {PLATFORM_PERMISSION_PROVIDER_JOBS}
            )
            _, total = JobsProviderListUseCase().execute(user=user, filters=filters, accessible_functions=accessible)
            assert total == 2

        def test_function_filter_denied_raises_provider_not_found(self, user, provider, function):
            """Function filter denied → ProviderNotFoundException."""
            filters = JobFilters(provider="my-provider", function="my-function")
            with pytest.raises(ProviderNotFoundException):
                JobsProviderListUseCase().execute(
                    user=user,
                    filters=filters,
                    accessible_functions=FunctionAccessResult(has_response=True, functions=[]),
                )

        def test_function_filter_not_in_db_raises_function_not_found(self, user, provider):
            """Function filter: access OK but function not in DB → FunctionNotFoundException."""
            filters = JobFilters(provider="my-provider", function="ghost-function")
            accessible = create_function_access_result(
                "my-provider", "ghost-function", {PLATFORM_PERMISSION_PROVIDER_JOBS}
            )
            with pytest.raises(FunctionNotFoundException):
                JobsProviderListUseCase().execute(user=user, filters=filters, accessible_functions=accessible)
