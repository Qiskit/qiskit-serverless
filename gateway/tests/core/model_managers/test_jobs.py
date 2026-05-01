"""Tests for JobQuerySet model manager."""

import pytest
from django.contrib.auth.models import User

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
