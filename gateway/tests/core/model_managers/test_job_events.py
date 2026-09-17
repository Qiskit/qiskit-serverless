"""Unit tests for JobEventQuerySet.add_status_event() updating the outbox row."""

from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from core.model_managers.job_events import JobEventContext, JobEventOrigin
from core.models import Job, JobEvent, JobOutbox, Program

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return User.objects.create_user(username="author")


@pytest.fixture
def job(user):
    return Job.objects.create(author=user, runner=Program.FLEETS, status=Job.QUEUED)


def _add_status_event(job, status):
    return JobEvent.objects.add_status_event(
        job_id=job.id,
        origin=JobEventOrigin.SCHEDULER,
        context=JobEventContext.UPDATE_JOB_STATUS,
        status=status,
    )


class TestNoOutboxRow:
    def test_does_not_create_a_row_and_does_not_raise(self, job):
        """Ray, filler, and pre-deployment jobs have no row; nothing should happen."""
        _add_status_event(job, Job.PENDING)

        assert JobOutbox.objects.count() == 0


class TestExistingOutboxRow:
    def test_updates_job_status_and_status_changed_at_from_the_events_own_created(self, job):
        JobOutbox.objects.create(
            job=job,
            job_status=Job.QUEUED,
            status_changed_at=timezone.now() - timedelta(hours=1),
            has_run=False,
            license_fee_required=True,
        )

        event = _add_status_event(job, Job.PENDING)

        row = JobOutbox.objects.get(job=job)
        assert row.job_status == Job.PENDING
        assert row.status_changed_at == event.created

    def test_sets_has_run_true_on_running_and_never_back_to_false(self, job):
        JobOutbox.objects.create(
            job=job,
            job_status=Job.PENDING,
            status_changed_at=timezone.now(),
            has_run=False,
            license_fee_required=True,
        )

        _add_status_event(job, Job.RUNNING)
        assert JobOutbox.objects.get(job=job).has_run is True

        _add_status_event(job, Job.SUCCEEDED)
        assert JobOutbox.objects.get(job=job).has_run is True

    def test_does_not_touch_license_fee_sent_at_or_billing_sent_at(self, job):
        """The funnel must never clear a sent marker: that would cause a resend."""
        sent = timezone.now() - timedelta(minutes=5)
        JobOutbox.objects.create(
            job=job,
            job_status=Job.RUNNING,
            status_changed_at=timezone.now(),
            has_run=True,
            license_fee_required=True,
            license_fee_sent_at=sent,
            billing_sent_at=sent,
        )

        _add_status_event(job, Job.SUCCEEDED)

        row = JobOutbox.objects.get(job=job)
        assert row.license_fee_sent_at == sent
        assert row.billing_sent_at == sent

    def test_pending_status_does_not_set_has_run(self, job):
        JobOutbox.objects.create(
            job=job,
            job_status=Job.QUEUED,
            status_changed_at=timezone.now(),
            has_run=False,
            license_fee_required=True,
        )

        _add_status_event(job, Job.PENDING)

        assert JobOutbox.objects.get(job=job).has_run is False
