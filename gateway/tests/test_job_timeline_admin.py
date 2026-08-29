"""Tests for the Job Timeline admin page."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from api.domain.job_timeline import render_job_timeline
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from core.models import Job, JobEvent, Program, Provider


def _job_with_events(status=Job.SUCCEEDED, compute_profile="bx3d-24x120", base=None):
    """Create one Job plus a QUEUED/PENDING/RUNNING/<status> JobEvent trail with known gaps.

    `JobEvent.created` and `Job.created` are `auto_now_add`, so Django ignores any value passed
    to `.create()` for them — the only way to control the timestamps is to create the rows first,
    then overwrite `created` with a bulk `.update()`, which issues a raw UPDATE and bypasses
    `auto_now_add` entirely. That's what the four `.update()` calls below are for.

    `base` defaults to "now" but can be passed in explicitly so two jobs share the exact same
    starting point (needed by the overlap test below — computing "now" twice, once per job,
    could in theory land a second apart and make the test flaky around a second boundary).
    """
    if base is None:
        base = timezone.now().replace(microsecond=0)
    user = User.objects.create_user(username=f"u{uuid4().hex[:8]}", password="x")
    provider = Provider.objects.create(name=f"P{uuid4().hex[:8]}")
    program = Program.objects.create(title="t", author=user, provider=provider)
    job = Job.objects.create(
        author=user, program=program, status=status, compute_profile=compute_profile, runner=Program.FLEETS
    )

    queued_event = job.job_events.add_status_event(
        job_id=job.id, origin=JobEventOrigin.API, context=JobEventContext.RUN_PROGRAM, status=Job.QUEUED
    )
    pending_event = job.job_events.add_status_event(
        job_id=job.id, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.SCHEDULE_JOBS, status=Job.PENDING
    )
    running_event = job.job_events.add_status_event(
        job_id=job.id, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS, status=Job.RUNNING
    )
    final_event = job.job_events.add_status_event(
        job_id=job.id, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS, status=status
    )

    JobEvent.objects.filter(pk=queued_event.pk).update(created=base)
    JobEvent.objects.filter(pk=pending_event.pk).update(created=base + timedelta(seconds=5))
    JobEvent.objects.filter(pk=running_event.pk).update(created=base + timedelta(seconds=51))
    JobEvent.objects.filter(pk=final_event.pk).update(created=base + timedelta(seconds=99))
    return job


@pytest.mark.django_db
def test_render_job_timeline_reports_per_state_durations_and_outcome():
    job = _job_with_events()

    context = render_job_timeline(Job.objects.filter(pk=job.pk).prefetch_related("job_events"))

    assert context["timeline_jobs_count"] == 1
    svg = context["timeline_svg"]
    assert str(job.id)[:8] in svg
    assert "PENDING: 46s" in svg  # pending ran from base+5s to base+51s
    assert "RUNNING: 48s" in svg  # running ran from base+51s to base+99s
    assert ">OK<" in svg  # SUCCEEDED outcome marker


@pytest.mark.django_db
def test_render_job_timeline_flags_overlapping_running_jobs():
    shared_base = timezone.now().replace(microsecond=0)
    job_a = _job_with_events(base=shared_base)
    job_b = _job_with_events(status=Job.FAILED, base=shared_base)

    context = render_job_timeline(Job.objects.filter(pk__in=[job_a.pk, job_b.pk]).prefetch_related("job_events"))

    # both jobs share the same base timestamp, so their RUNNING windows fully overlap
    assert "1 pares de jobs se solapan en ejecución" in context["timeline_overlap_summary"]


@pytest.mark.django_db
def test_timeline_action_redirects_to_a_page_that_renders_the_selected_jobs(client):
    job = _job_with_events()
    client.force_login(User.objects.create_superuser(username="admin", password="x", email="a@b.c"))

    response = client.post(
        reverse("admin:api_job_changelist"),
        data={"action": "timeline_action", "_selected_action": [str(job.pk)]},
    )

    assert response.status_code == 302
    assert response.url == reverse("admin:job_timeline_view") + f"?ids={job.pk}"

    page = client.get(response.url)
    assert page.status_code == 200
    assert str(job.id)[:8] in page.content.decode()


@pytest.mark.django_db
def test_timeline_view_redirects_to_changelist_with_no_selection(client):
    client.force_login(User.objects.create_superuser(username="admin", password="x", email="a@b.c"))

    response = client.get(reverse("admin:job_timeline_view"))

    assert response.status_code == 302
    assert response.url == reverse("admin:api_job_changelist")


@pytest.mark.django_db
def test_timeline_view_redirects_to_changelist_with_a_malformed_id(client):
    client.force_login(User.objects.create_superuser(username="admin", password="x", email="a@b.c"))

    response = client.get(reverse("admin:job_timeline_view") + "?ids=not-a-uuid")

    assert response.status_code == 302
    assert response.url == reverse("admin:api_job_changelist")
