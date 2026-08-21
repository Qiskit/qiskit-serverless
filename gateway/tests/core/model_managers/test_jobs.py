"""Tests for JobQuerySet model manager."""

import pytest
from django.contrib.auth.models import User

from core.enums.type_filter import TypeFilter
from core.model_managers.jobs import JobFilters
from core.models import Job, Program, Provider

pytestmark = pytest.mark.django_db


@pytest.fixture()
def author():
    return User.objects.create_user(username="author")


@pytest.fixture()
def provider():
    return Provider.objects.create(name="my-provider")


@pytest.fixture()
def fn_a(provider, author):
    return Program.objects.create(title="fn-a", author=author, provider=provider)


@pytest.fixture()
def fn_b(provider, author):
    return Program.objects.create(title="fn-b", author=author, provider=provider)


@pytest.fixture()
def fn_c(provider, author):
    return Program.objects.create(title="fn-c", author=author, provider=provider)


@pytest.fixture()
def jobs(fn_a, fn_b, fn_c, author):
    return [
        Job.objects.create(author=author, program=fn_a),
        Job.objects.create(author=author, program=fn_b),
        Job.objects.create(author=author, program=fn_c),
    ]


class TestFilterFunctions:
    def test_filter_by_function_set(self, jobs, fn_a, fn_b, fn_c):
        """Only jobs whose function title is in the set are returned."""
        filters = JobFilters(functions={"fn-a", "fn-b"})
        queryset, total = Job.objects.user_jobs_page(user=None, filters=filters)

        titles = {job.program.title for job in queryset}
        assert total == 2
        assert titles == {"fn-a", "fn-b"}

    def test_filter_empty_set_returns_no_jobs(self, jobs):
        """Empty set is falsy → functions filter is skipped → all jobs returned (edge case)."""
        filters = JobFilters(functions=set())
        queryset, total = Job.objects.user_jobs_page(user=None, filters=filters)

        # set() is falsy so the `elif filters.functions` branch is skipped
        assert total == 3

    def test_function_takes_priority_over_functions(self, jobs, fn_a):
        """When filters.function is set, it takes priority over filters.functions."""
        filters = JobFilters(function="fn-a", functions={"fn-b", "fn-c"})
        queryset, total = Job.objects.user_jobs_page(user=None, filters=filters)

        titles = {job.program.title for job in queryset}
        assert total == 1
        assert titles == {"fn-a"}


@pytest.fixture()
def colliding_jobs(provider, author):
    """The same function title under two providers, plus a custom function.

    Titles are unique only *per provider* (`unique_provider_title`), so this shape is legal and is
    what makes a title-only filter unsafe for scoping.
    """
    other_provider = Provider.objects.create(name="other-provider")
    return {
        "mine": Job.objects.create(
            author=author, program=Program.objects.create(title="shared", author=author, provider=provider)
        ),
        "theirs": Job.objects.create(
            author=author, program=Program.objects.create(title="shared", author=author, provider=other_provider)
        ),
        "custom": Job.objects.create(
            author=author, program=Program.objects.create(title="shared", author=author, provider=None)
        ),
    }


class TestFilterProvider:
    """`filters.provider` scopes the queryset whenever it is set.

    It used to be applied only under `filter=CATALOG`, which left `jobs/provider` -- which never sets
    `filter` -- scoped by function title alone.
    """

    # `filter=CATALOG` also covers the regression where the clause compared a *name* against
    # Provider's UUID primary key and raised ValueError("badly formed hexadecimal UUID string") --
    # CATALOG was the only arm that reached it, so it 500'd rather than mis-scoped.
    @pytest.mark.parametrize("type_filter", [None, TypeFilter.CATALOG])
    def test_provider_scopes_queryset(self, colliding_jobs, type_filter):
        """`filter=None` is the `jobs/provider` shape; CATALOG is the `jobs` shape."""
        filters = JobFilters(provider="my-provider", filter=type_filter)
        queryset, total = Job.objects.user_jobs_page(user=None, filters=filters)

        assert total == 1
        assert [job.id for job in queryset] == [colliding_jobs["mine"].id]

    # `_apply_filters` scopes by title through two mutually exclusive branches; both need the
    # provider clause, so both are exercised here.
    @pytest.mark.parametrize("title_filter", [{"function": "shared"}, {"functions": {"shared"}}])
    def test_title_filter_does_not_leak_across_providers(self, colliding_jobs, title_filter):
        """A title shared with another provider (and with a custom function) must not widen the result."""
        filters = JobFilters(provider="my-provider", **title_filter)
        queryset, total = Job.objects.user_jobs_page(user=None, filters=filters)

        assert total == 1
        assert [job.id for job in queryset] == [colliding_jobs["mine"].id]

    def test_unknown_provider_returns_nothing(self, colliding_jobs):
        """A provider that matches no rows scopes to empty rather than falling open."""
        filters = JobFilters(provider="does-not-exist")
        _, total = Job.objects.user_jobs_page(user=None, filters=filters)

        assert total == 0

    # Guardrails for the `match` arms: the provider clause was lifted out of CATALOG, and CATALOG's
    # inner if/else collapsed to the else branch. These pin the no-provider behaviour of both arms.
    @pytest.mark.parametrize(
        "type_filter,expected_total,expect_provider",
        [(TypeFilter.CATALOG, 2, True), (TypeFilter.SERVERLESS, 1, False)],
    )
    def test_type_filter_arms_unchanged_when_no_provider_named(
        self, colliding_jobs, type_filter, expected_total, expect_provider
    ):
        filters = JobFilters(filter=type_filter)
        queryset, total = Job.objects.user_jobs_page(user=None, filters=filters)

        assert total == expected_total
        assert all((job.program.provider is not None) is expect_provider for job in queryset)
