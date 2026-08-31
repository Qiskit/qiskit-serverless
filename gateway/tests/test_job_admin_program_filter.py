"""Tests for the 'By Program' sidebar filter on the Job admin changelist."""

import pytest
from django.contrib.auth.models import User
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext

from api.admin import JobAdmin, JobProgramFilter
from core.models import Job, Program, Provider


def _lookups(request):
    model_admin = JobAdmin(Job, None)
    return JobProgramFilter(request, {}, Job, model_admin).lookups(request, model_admin)


@pytest.mark.django_db
def test_job_program_filter_lookups_groups_by_provider_and_flags_custom():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    provider = Provider.objects.create(name="TestProvider")
    program = Program.objects.create(title="prog1", author=user, provider=provider)
    custom_program = Program.objects.create(title="custom-prog", author=user, provider=None)

    Job.objects.create(author=user, program=program, status=Job.SUCCEEDED)
    Job.objects.create(author=user, program=custom_program, status=Job.SUCCEEDED)
    Job.objects.create(author=user, program=None, status=Job.SUCCEEDED)

    choices = _lookups(RequestFactory().get("/backoffice/api/job/"))

    assert ("custom", "Custom") in choices
    assert (str(program.pk), "TestProvider / prog1") in choices


@pytest.mark.django_db
def test_job_program_filter_lookups_does_not_scale_with_distinct_programs():
    """Regression test: lookups() must not issue one extra query per distinct program (N+1)."""
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    provider = Provider.objects.create(name="TestProvider")
    for i in range(20):
        program = Program.objects.create(title=f"prog{i}", author=user, provider=provider)
        Job.objects.create(author=user, program=program, status=Job.SUCCEEDED)

    with CaptureQueriesContext(connection) as ctx:
        _lookups(RequestFactory().get("/backoffice/api/job/"))

    assert len(ctx.captured_queries) <= 5
