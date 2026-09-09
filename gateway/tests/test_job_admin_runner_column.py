"""Tests for the 'Runner' column on the Job admin changelist."""

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from api.admin import JobAdmin
from core.models import Job, Program


@pytest.mark.django_db
def test_runner_column_shows_fleet_id_link_for_fleets_job():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    job = Job.objects.create(author=user, runner=Program.FLEETS, fleet_id="fleet-123", status=Job.RUNNING)

    html = JobAdmin(Job, None).runner_column(job)

    assert f'href="{reverse("admin:api_job_change", args=[job.pk])}"' in html
    assert ">fleet-123<" in html
    assert "Fleets" in html


@pytest.mark.django_db
def test_runner_column_shows_ray_job_id_link_for_ray_job():
    user = User.objects.create_superuser(username="admin", password="x", email="a@a.com")
    job = Job.objects.create(author=user, runner=Program.RAY, ray_job_id="raysubmit_abc", status=Job.RUNNING)

    html = JobAdmin(Job, None).runner_column(job)

    assert ">raysubmit_abc<" in html
    assert "Ray" in html
