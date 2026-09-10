"""Tests for the Job admin changelist columns and their click-to-filter links."""

import pytest
from django.contrib.auth.models import User
from django.test import Client, RequestFactory
from django.urls import reverse

from api.admin import JobAdmin
from core.models import ComputeProfile, FunctionSize, Job, Program, Provider


def _changelist_url():
    return reverse("admin:api_job_changelist")


@pytest.mark.django_db
def test_runner_column_shows_fleet_id_as_a_code_chip_with_project_and_region():
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
    assert "Fleets" in html
    assert '<span class="qs-runner-meta">my-project us-south</span>' in html


@pytest.mark.django_db
def test_runner_column_shows_ray_job_id_with_no_project_or_region_line():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    job = Job.objects.create(author=user, runner=Program.RAY, ray_job_id="raysubmit_abc", status=Job.RUNNING)

    html = JobAdmin(Job, None).runner_column(job)

    assert '<span class="qs-runner-id" title="raysubmit_abc">raysubmit_abc</span>' in html
    assert "Ray" in html
    assert "qs-runner-meta" not in html


@pytest.mark.django_db
def test_author_column_filters_the_changelist_by_author_and_shows_instance_crn():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    job = Job.objects.create(author=user, status=Job.RUNNING, instance_crn="crn:v1:bluemix:public:my-service")

    html = JobAdmin(Job, None).author_column(job)

    assert f'href="{_changelist_url()}?author__id__exact={user.pk}"' in html
    assert ">admin<" in html
    assert f'href="{_changelist_url()}?instance_crn__exact=crn:v1:bluemix:public:my-service"' in html


@pytest.mark.django_db
def test_author_column_has_no_second_line_without_an_instance_crn():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    job = Job.objects.create(author=user, status=Job.RUNNING)

    html = JobAdmin(Job, None).author_column(job)

    assert "instance_crn" not in html
    assert "qs-runner-meta" not in html


@pytest.mark.django_db
def test_status_badge_links_to_the_changelist_filtered_by_that_status():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    job = Job.objects.create(author=user, status=Job.RUNNING)

    html = JobAdmin(Job, None).status_badge(job)

    assert f'href="{_changelist_url()}?status__exact=RUNNING"' in html


@pytest.mark.django_db
def test_get_program_filters_by_provider_and_by_program_with_no_space_around_the_slash():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    provider = Provider.objects.create(name="TestProvider")
    program = Program.objects.create(title="prog1", author=user, provider=provider)
    job = Job.objects.create(author=user, program=program, status=Job.RUNNING)

    html = JobAdmin(Job, None).get_program(job)

    assert f'href="{_changelist_url()}?program__provider__id__exact={provider.pk}"' in html
    assert f'href="{_changelist_url()}?job_program={program.pk}"' in html
    assert ">TestProvider</a>/<a " in html


@pytest.mark.django_db
def test_get_program_links_just_the_program_when_it_has_no_provider():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    program = Program.objects.create(title="custom-prog", author=user, provider=None)
    job = Job.objects.create(author=user, program=program, status=Job.RUNNING)

    html = JobAdmin(Job, None).get_program(job)

    assert f'href="{_changelist_url()}?job_program={program.pk}"' in html
    assert ">custom-prog</a>" in html


@pytest.mark.django_db
def test_lookup_allowed_permits_filtering_by_provider():
    request = RequestFactory().get("/backoffice/api/job/")
    assert JobAdmin(Job, None).lookup_allowed("program__provider__id__exact", "some-uuid", request) is True


@pytest.mark.django_db
def test_compute_profile_column_is_empty_for_a_ray_job():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    job = Job.objects.create(author=user, runner=Program.RAY, status=Job.RUNNING)

    assert JobAdmin(Job, None).compute_profile_column(job) == ""


@pytest.mark.django_db
def test_compute_profile_column_links_the_profile_and_shows_the_function_size_for_fleets():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    program = Program.objects.create(title="prog1", author=user, provider=None)
    profile = ComputeProfile.objects.create(compute_profile_id="24x120x1l40", cpu="24", memory="120")
    size = FunctionSize.objects.create(function=program, function_size="24x120x1l40", compute_profile=profile)
    job = Job.objects.create(
        author=user,
        runner=Program.FLEETS,
        status=Job.RUNNING,
        compute_profile_fk=profile,
        function_size=size,
    )

    html = JobAdmin(Job, None).compute_profile_column(job)

    assert f'href="{_changelist_url()}?compute_profile_fk__exact=24x120x1l40"' in html
    assert ">24x120x1l40<" in html
    assert str(size) in html


@pytest.mark.django_db
def test_changelist_accepts_every_click_to_filter_query_string():
    """Each link built by the columns above must actually be a lookup the admin accepts (no 400)."""
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    provider = Provider.objects.create(name="TestProvider")
    program = Program.objects.create(title="prog1", author=user, provider=provider)
    profile = ComputeProfile.objects.create(compute_profile_id="24x120x1l40", cpu="24", memory="120")
    Job.objects.create(
        author=user,
        program=program,
        status=Job.RUNNING,
        runner=Program.FLEETS,
        compute_profile_fk=profile,
        instance_crn="crn:v1:bluemix:public:my-service",
    )

    client = Client()
    client.force_login(user)
    query_strings = [
        f"author__id__exact={user.pk}",
        "status__exact=RUNNING",
        f"program__provider__id__exact={provider.pk}",
        f"job_program={program.pk}",
        "compute_profile_fk__exact=24x120x1l40",
        "instance_crn__exact=crn:v1:bluemix:public:my-service",
    ]

    for query_string in query_strings:
        response = client.get(f"/backoffice/api/job/?{query_string}")
        assert response.status_code == 200, f"{query_string} was rejected"
