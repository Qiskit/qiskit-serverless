"""Unit tests for JobsProviderListUseCase."""

import pytest
from django.contrib.auth.models import Group, User

from core.domain.authorization.function_access_result import FunctionAccessResult
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.domain.exceptions.provider_not_found_exception import ProviderNotFoundException
from api.use_cases.jobs.provider_list import JobsProviderListUseCase
from core.model_managers.jobs import JobFilters
from core.models import Job, PLATFORM_PERMISSION_JOBS_READ, Program, Provider
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
def function_owner():
    """Author of the functions under test.

    Deliberately NOT `user`: ownership grants every provider operation, so functions authored
    by the caller would make the access-denied assertions below pass for the wrong reason.
    """
    return User.objects.create_user(username="function-owner")


@pytest.fixture()
def function(provider, function_owner):
    return Program.objects.create(title="my-function", author=function_owner, provider=provider)


@pytest.fixture()
def function_owned_by_caller(provider, user):
    """The same function, but authored by the caller -- for the ownership-bypass test."""
    return Program.objects.create(title="my-function", author=user, provider=provider)


@pytest.fixture()
def jobs(function, user, admin_user):
    j1 = Job.objects.create(author=user, program=function)
    j2 = Job.objects.create(author=admin_user, program=function)
    return [j1, j2]


@pytest.fixture()
def function_a(provider, function_owner):
    return Program.objects.create(title="function-a", author=function_owner, provider=provider)


@pytest.fixture()
def function_b(provider, function_owner):
    return Program.objects.create(title="function-b", author=function_owner, provider=provider)


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
                ({PLATFORM_PERMISSION_JOBS_READ}, 2),
                ({"other-permission"}, None),
            ],
        )
        def test_access_depends_on_provider_jobs_permission(
            self, user, provider, function, jobs, permissions, expected_total
        ):
            """Only PLATFORM_PERMISSION_JOBS_READ grants access; any other permission hides the provider."""
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
            accessible = create_function_access_result("my-provider", function_filter, {PLATFORM_PERMISSION_JOBS_READ})
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


class TestOwnership:
    """The unfiltered provider job list degrades to "jobs of the functions you author".

    `_check` answers a question about one named function, and there is no function filter here,
    so these branches consult ownership directly via `_owned_function_titles`.
    """

    def test_owner_without_function_filter_sees_own_function_jobs(self, user, provider, function_owned_by_caller):
        """An owner who is neither admin nor entitled now gets their own function's jobs."""
        Job.objects.create(author=user, program=function_owned_by_caller)
        filters = JobFilters(provider="my-provider", limit=20, offset=0)

        result_jobs, total = JobsProviderListUseCase().execute(
            user=user,
            filters=filters,
            accessible_functions=FunctionAccessResult(use_legacy_authorization=False, functions=[]),
        )

        assert total == 1
        assert [job.program.title for job in result_jobs] == ["my-function"]

    def test_owner_without_function_filter_sees_own_function_jobs_on_legacy_path(
        self, user, provider, function_owned_by_caller
    ):
        """Same on the legacy path: not a provider admin, but the author of the function."""
        Job.objects.create(author=user, program=function_owned_by_caller)
        filters = JobFilters(provider="my-provider", limit=20, offset=0)

        result_jobs, total = JobsProviderListUseCase().execute(
            user=user,
            filters=filters,
            accessible_functions=FunctionAccessResult(use_legacy_authorization=True),
        )

        assert total == 1
        assert [job.program.title for job in result_jobs] == ["my-function"]

    def test_owned_titles_union_with_entitled_titles(self, user, provider, function_owner, admin_user):
        """Entitlements and ownership add up rather than one replacing the other."""
        entitled = Program.objects.create(title="entitled-fn", author=function_owner, provider=provider)
        owned = Program.objects.create(title="owned-fn", author=user, provider=provider)
        unrelated = Program.objects.create(title="unrelated-fn", author=function_owner, provider=provider)
        Job.objects.create(author=admin_user, program=entitled)
        Job.objects.create(author=admin_user, program=owned)
        Job.objects.create(author=admin_user, program=unrelated)

        filters = JobFilters(provider="my-provider", limit=20, offset=0)
        accessible = create_function_access_result("my-provider", "entitled-fn", {PLATFORM_PERMISSION_JOBS_READ})

        result_jobs, total = JobsProviderListUseCase().execute(
            user=user, filters=filters, accessible_functions=accessible
        )

        assert total == 2
        assert sorted(job.program.title for job in result_jobs) == ["entitled-fn", "owned-fn"]

    def test_ownership_does_not_cross_providers(self, user, function_owner):
        """Owning provider-a/my-fn must not open up provider-b's job list."""
        provider_a = Provider.objects.create(name="provider-a")
        provider_b = Provider.objects.create(name="provider-b")
        Program.objects.create(title="my-fn", author=user, provider=provider_a)
        fn_b = Program.objects.create(title="my-fn", author=function_owner, provider=provider_b)
        Job.objects.create(author=user, program=fn_b)

        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        with pytest.raises(ProviderNotFoundException):
            JobsProviderListUseCase().execute(
                user=user,
                filters=JobFilters(provider="provider-b", limit=20, offset=0),
                accessible_functions=accessible,
            )
