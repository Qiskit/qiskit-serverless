"""Unit tests for JobEventQuerySet.add_status_event() updating the outbox row."""

from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from core.model_managers.job_events import JobEventContext, JobEventOrigin, JobEventType
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


class TestTransitionStatus:
    """Unit tests for JobEventQuerySet.transition_status()."""

    def test_persists_status_and_job_fields(self, job):
        JobEvent.objects.transition_status(
            job,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.UPDATE_JOB_STATUS,
            status=Job.RUNNING,
            job_fields={"sub_status": "mapping"},
        )

        job.refresh_from_db()
        assert job.status == Job.RUNNING
        assert job.sub_status == "mapping"

    def test_creates_the_status_change_event(self, job):
        event = JobEvent.objects.transition_status(
            job,
            origin=JobEventOrigin.API,
            context=JobEventContext.STOP_JOB,
            status=Job.STOPPED,
        )

        assert event.data == {"status": Job.STOPPED}
        assert event.origin == JobEventOrigin.API
        assert event.context == JobEventContext.STOP_JOB

    def test_rolls_back_the_event_if_the_job_write_fails(self, job, monkeypatch):
        """Event-then-job must be all-or-nothing: a failed job write must not leave
        a JobEvent behind with no matching state change."""

        def _boom(self, fields_map):  # pylint: disable=unused-argument
            raise RuntimeError("boom")

        monkeypatch.setattr(Job, "update_fields", _boom)

        with pytest.raises(RuntimeError, match="boom"):
            JobEvent.objects.transition_status(
                job,
                origin=JobEventOrigin.SCHEDULER,
                context=JobEventContext.UPDATE_JOB_STATUS,
                status=Job.RUNNING,
            )

        assert JobEvent.objects.filter(job=job).count() == 0


class TestFirstRunningAt:
    """Unit tests for JobEventQuerySet.first_running_at()."""

    def test_returns_none_when_the_job_never_ran(self, job):
        assert JobEvent.objects.first_running_at(job.id) is None

    def test_returns_the_created_timestamp_of_the_running_event(self, job):
        event = _add_status_event(job, Job.RUNNING)

        assert JobEvent.objects.first_running_at(job.id) == event.created

    def test_returns_the_first_one_not_the_latest(self, job):
        first = _add_status_event(job, Job.RUNNING)
        _add_status_event(job, Job.SUCCEEDED)
        _add_status_event(job, Job.RUNNING)  # unusual, but must not shadow the first one

        assert JobEvent.objects.first_running_at(job.id) == first.created

    def test_ignores_non_status_change_events_even_if_data_has_a_status_key(self, job):
        JobEvent.objects.create(
            job_id=job.id,
            origin=JobEventOrigin.API,
            context=JobEventContext.SEND_ERROR,
            event_type=JobEventType.ERROR,
            data={"status": Job.RUNNING},
        )

        assert JobEvent.objects.first_running_at(job.id) is None
