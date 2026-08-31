"""Tests for the Job Timeline admin page."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from api.domain.job_timeline import render_job_timeline
from core.domain.business_models import BusinessModel
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from core.models import Job, JobEvent, Program, Provider


def _job_with_events(
    status=Job.SUCCEEDED, compute_profile="bx3d-24x120", base=None, runner=Program.FLEETS, **extra_fields
):
    """Create one Job plus a QUEUED/PENDING/RUNNING/<status> JobEvent trail with known gaps.

    `JobEvent.created` and `Job.created` are `auto_now_add`, so Django ignores any value passed
    to `.create()` for them — the only way to control the timestamps is to create the rows first,
    then overwrite `created` with a bulk `.update()`, which issues a raw UPDATE and bypasses
    `auto_now_add` entirely. That's what the four `.update()` calls below are for.

    `base` defaults to "now" but can be passed in explicitly so two jobs share the exact same
    starting point (needed by the overlap test below — computing "now" twice, once per job,
    could in theory land a second apart and make the test flaky around a second boundary).

    `extra_fields` is forwarded straight to `Job.objects.create` (e.g. `account_id=...`), for
    tests that need to check the job details panel.
    """
    if base is None:
        base = timezone.now().replace(microsecond=0)
    user = User.objects.create_user(username=f"u{uuid4().hex[:8]}", password="x")
    provider = Provider.objects.create(name=f"P{uuid4().hex[:8]}")
    program = Program.objects.create(title="t", author=user, provider=provider)
    job = Job.objects.create(
        author=user,
        program=program,
        status=status,
        compute_profile=compute_profile,
        runner=runner,
        **extra_fields,
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
    # pending ran from base+5s to base+51s, running from base+51s to base+99s: both segments
    # are wide enough in a single-job chart to carry their own duration inline
    assert ">46s<" in svg
    assert ">48s<" in svg
    assert ">SUCCEEDED<" in svg  # same wording as the job list's status badge


@pytest.mark.django_db
def test_render_job_timeline_extends_an_unfinished_job_up_to_now():
    base = timezone.now().replace(microsecond=0) - timedelta(minutes=10)
    job = _job_with_events(status=Job.RUNNING, base=base)

    context = render_job_timeline(Job.objects.filter(pk=job.pk).prefetch_related("job_events"))

    # RUNNING started at base+51s and the job has not finished, so its RUNNING segment runs on
    # until now: ten minutes minus those 51 seconds, that is nine minutes and change
    assert ">9m " in context["timeline_svg"]


@pytest.mark.django_db
def test_render_job_timeline_flags_overlapping_running_jobs():
    shared_base = timezone.now().replace(microsecond=0)
    job_a = _job_with_events(base=shared_base)
    job_b = _job_with_events(status=Job.FAILED, base=shared_base)

    context = render_job_timeline(Job.objects.filter(pk__in=[job_a.pk, job_b.pk]).prefetch_related("job_events"))

    # both jobs share the same base timestamp, so their RUNNING windows fully overlap: each
    # job's row label gets a "overlaps with 1 other job" badge
    assert context["timeline_svg"].count("⧉1") == 2


@pytest.mark.django_db
def test_render_job_timeline_does_not_flag_overlaps_across_runners():
    shared_base = timezone.now().replace(microsecond=0)
    job_ray = _job_with_events(base=shared_base, runner=Program.RAY)
    job_fleets = _job_with_events(status=Job.FAILED, base=shared_base, runner=Program.FLEETS)

    context = render_job_timeline(Job.objects.filter(pk__in=[job_ray.pk, job_fleets.pk]).prefetch_related("job_events"))

    # same RUNNING window, but Ray and Fleets run on separate infrastructure, so neither job
    # should be flagged as overlapping the other
    assert "⧉" not in context["timeline_svg"]


@pytest.mark.django_db
def test_render_job_timeline_orders_jobs_by_creation_most_recent_first():
    job_old = _job_with_events()
    job_new = _job_with_events()

    context = render_job_timeline(Job.objects.filter(pk__in=[job_old.pk, job_new.pk]).prefetch_related("job_events"))

    svg = context["timeline_svg"]
    assert svg.index(str(job_new.id)[:8]) < svg.index(str(job_old.id)[:8])


@pytest.mark.django_db
def test_render_job_timeline_builds_a_runner_filter_bar():
    job = _job_with_events(runner=Program.RAY)

    context = render_job_timeline(Job.objects.filter(pk=job.pk).prefetch_related("job_events"))

    assert 'data-runner="ray"' in context["timeline_runner_filter_bar"]
    assert "Ray" in context["timeline_runner_filter_bar"]


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


@pytest.mark.django_db
def test_timeline_view_redirects_to_changelist_when_no_job_matches_the_ids(client):
    client.force_login(User.objects.create_superuser(username="admin", password="x", email="a@b.c"))

    response = client.get(reverse("admin:job_timeline_view") + f"?ids={uuid4()}")

    assert response.status_code == 302
    assert response.url == reverse("admin:api_job_changelist")


@pytest.mark.django_db
def test_render_job_timeline_escapes_a_compute_profile_that_looks_like_markup():
    # the compute profile is shown both on the chart label and in the job details panel
    job = _job_with_events(compute_profile="<script>alert(1)</script>")

    context = render_job_timeline(Job.objects.filter(pk=job.pk).prefetch_related("job_events"))

    assert "<script>" not in context["timeline_svg"]
    assert "<script>" not in context["timeline_job_details"]
    assert "&lt;script&gt;" in context["timeline_svg"]
    assert "&lt;script&gt;" in context["timeline_job_details"]


@pytest.mark.django_db
def test_render_job_timeline_shows_job_and_fleets_details():
    job = _job_with_events(
        business_model=BusinessModel.TRIAL,
        account_id="acct-1",
        instance_crn="crn:v1:bluemix:public:quantum-computing::a/acct-1:instance-1",
        fleet_id="fleet-1",
        ce_project_name="proj-1",
        ce_region="us-south",
    )

    context = render_job_timeline(Job.objects.filter(pk=job.pk).select_related("author").prefetch_related("job_events"))

    details = context["timeline_job_details"]
    assert f'data-job-id="{job.id}"' in details
    assert job.author.username in details
    assert BusinessModel.TRIAL in details
    assert "acct-1" in details
    assert "crn:v1:bluemix:public:quantum-computing::a/acct-1:instance-1" in details
    assert "fleet-1" in details
    assert "bx3d-24x120" in details  # compute_profile, listed under "Fleets"
    assert "proj-1" in details
    assert "us-south" in details
    assert f'data-job-id="{job.id}"' in context["timeline_svg"]  # the row itself is clickable
