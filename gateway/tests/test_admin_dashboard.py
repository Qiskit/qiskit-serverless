"""Tests for the admin dashboard stats function."""

import pytest
from django.contrib.auth.models import User

from api.admin import get_dashboard_stats
from core.models import CodeEngineProject, Job, Program, Provider


@pytest.mark.django_db
def test_get_dashboard_stats_empty_db():
    stats = get_dashboard_stats()

    assert stats["providers_count"] == 0
    assert stats["providers_active"] == 0
    assert stats["programs_count"] == 0
    assert stats["programs_disabled"] == 0
    assert stats["jobs_count"] == 0
    assert stats["jobs_active"] == 0
    assert stats["ce_projects_count"] == 0
    assert stats["ce_projects_active"] == 0
    assert stats["jobs_by_status"] == []
    assert stats["jobs_by_provider"] == []


@pytest.mark.django_db
def test_get_dashboard_stats_with_data():
    user = User.objects.create_user(username="testuser", password="x")
    provider = Provider.objects.create(name="TestProvider")
    program = Program.objects.create(title="prog1", author=user, provider=provider)
    Job.objects.create(author=user, program=program, status=Job.SUCCEEDED)
    Job.objects.create(author=user, program=program, status=Job.SUCCEEDED)
    Job.objects.create(author=user, program=program, status=Job.RUNNING)
    CodeEngineProject.objects.create(project_name="proj1", project_id="id1", region="us-south")

    stats = get_dashboard_stats()

    assert stats["providers_count"] == 1
    assert stats["programs_count"] == 1
    assert stats["jobs_count"] == 3
    assert stats["jobs_active"] == 1  # only RUNNING is in ACTIVE_STATUSES
    assert stats["ce_projects_count"] == 1
    assert stats["ce_projects_active"] == 1

    statuses = {row["status"]: row["count"] for row in stats["jobs_by_status"]}
    assert statuses[Job.SUCCEEDED] == 2
    assert statuses[Job.RUNNING] == 1

    providers = {row["name"]: row["count"] for row in stats["jobs_by_provider"]}
    assert providers["TestProvider"] == 3


@pytest.mark.django_db
def test_get_dashboard_stats_custom_jobs():
    """Jobs with no program or no provider are grouped as Custom."""
    user = User.objects.create_user(username="testuser2", password="x")
    Job.objects.create(author=user, program=None, status=Job.FAILED)

    stats = get_dashboard_stats()

    providers = {row["name"]: row["count"] for row in stats["jobs_by_provider"]}
    assert providers["Custom"] == 1


@pytest.mark.django_db
def test_get_dashboard_stats_pct_sums_to_100():
    user = User.objects.create_user(username="testuser3", password="x")
    for _ in range(3):
        Job.objects.create(author=user, status=Job.SUCCEEDED)
    for _ in range(1):
        Job.objects.create(author=user, status=Job.FAILED)

    stats = get_dashboard_stats()

    total_pct = sum(row["pct"] for row in stats["jobs_by_status"])
    assert total_pct == 100
