"""Tests for the Job admin changelist columns and their click-to-search links."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils.http import urlencode

from api.admin import JobAdmin
from core.models import ComputeProfile, FunctionSize, Job, Program, Provider


def _search_url(value):
    return f"{reverse('admin:api_job_changelist')}?{urlencode({'q': value})}"


@pytest.mark.django_db
def test_runner_column_shows_fleet_id_as_a_code_chip_with_project_and_region_below_and_no_fleets_label():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    job = Job.objects.create(
        author=user,
        runner=Program.FLEETS,
        fleet_id="fleet-123",
        status=Job.RUNNING,
        ce_project_name="my-project",
        ce_region="us-south",
    )

    html = JobAdmin(Job, None).runner_column(job)

    assert '<span class="qs-runner-id" title="fleet-123">fleet-123</span>' in html
    assert '<span class="qs-runner-meta">my-project us-south</span>' in html
    # The column header already says Fleets, so the engine name is only spelled out for Ray.
    assert "Fleets" not in html
    # A real line break, not the literal text "<br>".
    assert html.count("<br>") == 1
    assert "&lt;br&gt;" not in html


@pytest.mark.django_db
def test_runner_column_leaves_the_chip_out_entirely_when_there_is_no_engine_job_id():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    job = Job.objects.create(author=user, runner=Program.FLEETS, status=Job.QUEUED, ce_project_name="my-project")

    html = JobAdmin(Job, None).runner_column(job)

    assert "qs-runner-id" not in html
    assert ">-<" not in html
    assert '<span class="qs-runner-meta">my-project</span>' in html
    assert "<br>" not in html


@pytest.mark.django_db
def test_runner_column_truncates_a_long_ray_job_id_to_12_chars_plus_ellipsis_but_keeps_the_full_value_as_title():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    job = Job.objects.create(author=user, runner=Program.RAY, ray_job_id="raysubmit_abcdef", status=Job.RUNNING)

    html = JobAdmin(Job, None).runner_column(job)

    assert '<span class="qs-runner-id" title="raysubmit_abcdef">raysubmit_ab…</span>' in html
    assert '<span class="qs-runner-label">Ray</span>' in html
    assert "qs-runner-meta" not in html
    assert html.count("<br>") == 1
    assert "&lt;br&gt;" not in html


@pytest.mark.django_db
def test_id_column_shows_a_12_char_chip_of_the_uuid_plus_ellipsis_with_the_full_value_as_title():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    job = Job.objects.create(author=user, status=Job.RUNNING)

    html = JobAdmin(Job, None).id_column(job)

    full_id = str(job.pk)
    assert f'<span class="qs-runner-id" title="{full_id}">{full_id[:12]}…</span>' in html
    assert len(full_id) > 12


@pytest.mark.django_db
def test_author_column_searches_for_the_author_and_shows_instance_crn_on_its_own_line():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    job = Job.objects.create(author=user, status=Job.RUNNING, instance_crn="crn:v1:bluemix:public:my-service")

    html = JobAdmin(Job, None).author_column(job)

    assert f'href="{_search_url("admin")}" class="qs-cell-link"' in html
    assert ">admin<" in html
    assert f'href="{_search_url("crn:v1:bluemix:public:my-service")}"' in html
    assert html.count("<br>") == 1
    assert "&lt;br&gt;" not in html


@pytest.mark.django_db
def test_author_column_has_no_second_line_without_an_instance_crn():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    job = Job.objects.create(author=user, status=Job.RUNNING)

    html = JobAdmin(Job, None).author_column(job)

    assert "instance_crn" not in html
    assert "qs-runner-meta" not in html
    assert "<br>" not in html


@pytest.mark.django_db
def test_status_badge_searches_for_that_status():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    job = Job.objects.create(author=user, status=Job.RUNNING)

    html = JobAdmin(Job, None).status_badge(job)

    assert f'href="{_search_url("RUNNING")}"' in html


@pytest.mark.django_db
def test_get_program_shows_the_function_name_with_its_provider_on_a_second_line():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    provider = Provider.objects.create(name="TestProvider")
    program = Program.objects.create(title="prog1", author=user, provider=provider)
    job = Job.objects.create(author=user, program=program, status=Job.RUNNING)

    html = JobAdmin(Job, None).get_program(job)

    assert f'<a href="{_search_url("prog1")}" class="qs-cell-link">prog1</a>' in html
    assert (
        f'<span class="qs-runner-meta">Provider: <a href="{_search_url("TestProvider")}">TestProvider</a></span>'
        in html
    )
    assert html.count("<br>") == 1
    assert "&lt;br&gt;" not in html


@pytest.mark.django_db
def test_get_program_says_custom_below_a_function_that_has_no_provider():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    program = Program.objects.create(title="custom-prog", author=user, provider=None)
    job = Job.objects.create(author=user, program=program, status=Job.RUNNING)

    html = JobAdmin(Job, None).get_program(job)

    assert f'<a href="{_search_url("custom-prog")}" class="qs-cell-link">custom-prog</a>' in html
    assert '<span class="qs-runner-meta">Custom</span>' in html
    assert "Provider:" not in html
    assert html.count("<br>") == 1


@pytest.mark.django_db
def test_compute_profile_column_is_empty_for_a_ray_job():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    job = Job.objects.create(author=user, runner=Program.RAY, status=Job.RUNNING)

    assert JobAdmin(Job, None).compute_profile_column(job) == ""


@pytest.mark.django_db
def test_compute_profile_column_searches_by_the_profile_and_shows_the_function_size_name_for_fleets():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    program = Program.objects.create(title="prog1", author=user, provider=None)
    profile = ComputeProfile.objects.create(compute_profile_id="24x120x1l40", cpu="24", memory="120")
    size = FunctionSize.objects.create(function=program, function_size="medium", compute_profile=profile)
    job = Job.objects.create(
        author=user,
        runner=Program.FLEETS,
        status=Job.RUNNING,
        compute_profile_fk=profile,
        function_size=size,
    )

    html = JobAdmin(Job, None).compute_profile_column(job)

    assert f'href="{_search_url("24x120x1l40")}"' in html
    assert 'class="qs-cell-link"' in html
    assert ">24x120x1l40<" in html
    # The size's own name, not its primary key nor the "program (size)" label of str(FunctionSize).
    assert '<span class="qs-runner-meta">medium</span>' in html
    assert str(size.pk) not in html
    assert html.count("<br>") == 1
    assert "&lt;br&gt;" not in html


@pytest.mark.django_db
def test_every_click_to_search_link_actually_narrows_the_changelist_to_that_job():
    """End-to-end: each search string built by the columns above finds the job it was built from."""
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    provider = Provider.objects.create(name="TestProvider")
    program = Program.objects.create(title="prog1", author=user, provider=provider)
    profile = ComputeProfile.objects.create(compute_profile_id="24x120x1l40", cpu="24", memory="120")
    job = Job.objects.create(
        author=user,
        program=program,
        status=Job.RUNNING,
        runner=Program.FLEETS,
        compute_profile_fk=profile,
        instance_crn="crn:v1:bluemix:public:my-service",
    )

    client = Client()
    client.force_login(user)
    search_terms = [
        "admin",
        "RUNNING",
        "TestProvider",
        "prog1",
        "24x120x1l40",
        "crn:v1:bluemix:public:my-service",
    ]

    for term in search_terms:
        response = client.get(_search_url(term))
        assert response.status_code == 200, f"{term!r} was rejected"
        assert str(job.pk) in response.content.decode(), f"{term!r} did not find the job"


@pytest.mark.django_db
def test_changelist_marks_created_and_updated_cells_for_the_smaller_font_css():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    Job.objects.create(author=user, status=Job.RUNNING)

    client = Client()
    client.force_login(user)
    body = client.get("/backoffice/api/job/").content.decode()

    assert "field-created" in body
    assert "field-updated" in body
