"""Unit tests for JobsProviderListUseCase."""

import pytest
from django.contrib.auth.models import Group, User

from api.domain.authorization.function_access_result import FunctionAccessResult
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.domain.exceptions.provider_not_found_exception import ProviderNotFoundException
from api.use_cases.jobs.provider_list import JobsProviderListUseCase
from core.model_managers.jobs import JobFilters
from core.models import Job, PLATFORM_PERMISSION_PROVIDER_JOBS, Program, Provider
from tests.utils import create_function_access_result

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


@pytest.fixture()
def function_a(provider, user):
    return Program.objects.create(title="function-a", author=user, provider=provider)


@pytest.fixture()
def function_b(provider, user):
    return Program.objects.create(title="function-b", author=user, provider=provider)


@pytest.fixture()
def jobs_two_functions(function_a, function_b, user, admin_user):
    j1 = Job.objects.create(author=user, program=function_a)
    j2 = Job.objects.create(author=admin_user, program=function_a)
    j3 = Job.objects.create(author=user, program=function_b)
    j4 = Job.objects.create(author=admin_user, program=function_b)
    return [j1, j2, j3, j4]


def _no_response():
    return FunctionAccessResult(use_legacy_authorization=True)


class TestProviderNotFound:
    def test_raises_when_provider_does_not_exist(self, user):
        filters = JobFilters(provider="nonexistent")
        with pytest.raises(ProviderNotFoundException):
            JobsProviderListUseCase().execute(user=user, filters=filters, accessible_functions=_no_response())


class TestListJobs:
    class TestLegacyGroups:
        def test_admin_can_list_all_jobs(self, admin_user, provider_with_admin, function, jobs):
            """User in provider admin_groups sees all jobs for that provider (legacy groups path)."""
            filters = JobFilters(provider="my-provider")
            _, total = JobsProviderListUseCase().execute(
                user=admin_user, filters=filters, accessible_functions=_no_response()
            )
            assert total == 2

        def test_non_admin_raises_provider_not_found(self, user, provider_with_admin):
            """User not in provider admin_groups gets ProviderNotFoundException (provider is hidden, not forbidden)."""
            filters = JobFilters(provider="my-provider")
            with pytest.raises(ProviderNotFoundException):
                JobsProviderListUseCase().execute(user=user, filters=filters, accessible_functions=_no_response())

        @pytest.mark.parametrize(
            "function_filter,expected",
            [
                ("function-a", 2),
                ("function-b", 2),
                ("ghost-function", FunctionNotFoundException),
            ],
        )
        def test_admin_filter_by_function_name(
            self, admin_user, provider_with_admin, function_a, function_b, jobs_two_functions, function_filter, expected
        ):
            """Admin sees only jobs of the requested function; a function not in DB raises FunctionNotFoundException."""
            filters = JobFilters(provider="my-provider", function=function_filter)
            if expected is FunctionNotFoundException:
                with pytest.raises(FunctionNotFoundException):
                    JobsProviderListUseCase().execute(
                        user=admin_user, filters=filters, accessible_functions=_no_response()
                    )
            else:
                result_jobs, total = JobsProviderListUseCase().execute(
                    user=admin_user, filters=filters, accessible_functions=_no_response()
                )
                assert total == expected
                assert all(job.program.title == function_filter for job in result_jobs)

        def test_non_admin_with_function_filter_raises(self, user, provider_with_admin, function):
            """User not in admin_groups gets ProviderNotFoundException even when filtering by a valid function."""
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
            """Only PLATFORM_PERMISSION_PROVIDER_JOBS grants access; any other permission hides the provider."""
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
            """accessible_functions.functions=[] (no accessible functions) hides the provider with ProviderNotFoundException."""
            filters = JobFilters(provider="my-provider")
            with pytest.raises(ProviderNotFoundException):
                JobsProviderListUseCase().execute(
                    user=user,
                    filters=filters,
                    accessible_functions=FunctionAccessResult(use_legacy_authorization=False, functions=[]),
                )

        @pytest.mark.parametrize(
            "function_filter,expected",
            [
                ("function-a", 2),
                ("function-b", 2),
                ("ghost-function", FunctionNotFoundException),
            ],
        )
        def test_function_filter_returns_correct_jobs(
            self, user, provider, function_a, function_b, jobs_two_functions, function_filter, expected
        ):
            """Filter by function name returns only that function's jobs;
            a function not in DB raises FunctionNotFoundException even if access is granted."""
            filters = JobFilters(provider="my-provider", function=function_filter)
            accessible = create_function_access_result(
                "my-provider", function_filter, {PLATFORM_PERMISSION_PROVIDER_JOBS}
            )
            if expected is FunctionNotFoundException:
                with pytest.raises(FunctionNotFoundException):
                    JobsProviderListUseCase().execute(user=user, filters=filters, accessible_functions=accessible)
            else:
                result_jobs, total = JobsProviderListUseCase().execute(
                    user=user, filters=filters, accessible_functions=accessible
                )
                assert total == expected
                assert all(job.program.title == function_filter for job in result_jobs)

        def test_function_filter_denied_raises_provider_not_found(self, user, provider, function):
            """accessible_functions.functions=[] means the requested function isn't accessible, hiding the provider with ProviderNotFoundException."""
            filters = JobFilters(provider="my-provider", function="my-function")
            with pytest.raises(ProviderNotFoundException):
                JobsProviderListUseCase().execute(
                    user=user,
                    filters=filters,
                    accessible_functions=FunctionAccessResult(use_legacy_authorization=False, functions=[]),
                )
