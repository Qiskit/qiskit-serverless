"""Tests for the Job admin changelist columns: Id link, Fleet Id chip, Author and Program links."""

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from api.admin import JobAdmin
from core.models import Job, Program, Provider


@pytest.mark.django_db
def test_runner_column_shows_fleet_id_as_a_code_chip_for_fleets_job():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    job = Job.objects.create(author=user, runner=Program.FLEETS, fleet_id="fleet-123", status=Job.RUNNING)

    html = JobAdmin(Job, None).runner_column(job)

    assert "<a href" not in html
    assert '<span class="qs-runner-id" title="fleet-123">fleet-123</span>' in html
    assert "Fleets" in html


@pytest.mark.django_db
def test_runner_column_shows_ray_job_id_for_ray_job():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    job = Job.objects.create(author=user, runner=Program.RAY, ray_job_id="raysubmit_abc", status=Job.RUNNING)

    html = JobAdmin(Job, None).runner_column(job)

    assert '<span class="qs-runner-id" title="raysubmit_abc">raysubmit_abc</span>' in html
    assert "Ray" in html


@pytest.mark.django_db
def test_author_column_links_to_the_user_admin_page():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    job = Job.objects.create(author=user, status=Job.RUNNING)

    html = JobAdmin(Job, None).author_column(job)

    assert f'href="{reverse("admin:auth_user_change", args=[user.pk])}"' in html
    assert ">admin<" in html


@pytest.mark.django_db
def test_get_program_links_provider_and_program_with_no_space_around_the_slash():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    provider = Provider.objects.create(name="TestProvider")
    program = Program.objects.create(title="prog1", author=user, provider=provider)
    job = Job.objects.create(author=user, program=program, status=Job.RUNNING)

    html = JobAdmin(Job, None).get_program(job)

    assert f'href="{reverse("admin:api_provider_change", args=[provider.pk])}"' in html
    assert f'href="{reverse("admin:api_program_change", args=[program.pk])}"' in html
    assert ">TestProvider</a>/<a " in html


@pytest.mark.django_db
def test_get_program_links_just_the_program_when_it_has_no_provider():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    program = Program.objects.create(title="custom-prog", author=user, provider=None)
    job = Job.objects.create(author=user, program=program, status=Job.RUNNING)

    html = JobAdmin(Job, None).get_program(job)

    assert f'href="{reverse("admin:api_program_change", args=[program.pk])}"' in html
    assert ">custom-prog</a>" in html
