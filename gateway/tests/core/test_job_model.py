"""Tests for Job model fields."""

from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from core.model_managers.job_events import JobEventContext, JobEventOrigin
from core.models import Job, JobEvent, JobOutbox, Program

pytestmark = pytest.mark.django_db


def _job_with_outbox(username, status=Job.QUEUED, has_run=False, **outbox_overrides):
    """A Fleets job plus the outbox row a real submission would have created for it."""
    author = User.objects.create_user(username=username)
    job = Job.objects.create(author=author, runner=Program.FLEETS, status=status)
    row = JobOutbox.objects.create(
        job=job,
        job_status=status,
        status_changed_at=timezone.now() - timedelta(hours=1),
        has_run=has_run,
        license_fee_required=True,
        **outbox_overrides,
    )
    return job, row


def test_filler_defaults_to_false_and_is_queryable():
    """A job created without filler is a real job, and the column can be filtered on."""
    author = User.objects.create_user(username="filler-test-author")
    job = Job.objects.create(author=author)

    assert job.filler is False
    assert Job.objects.filter(filler=False).count() == 1

    job.filler = True
    job.save()

    assert Job.objects.filter(filler=True).count() == 1


def test_filler_partial_index_is_declared():
    """A partial index on created covers the filler lookup the scheduler runs every second."""
    index = next((i for i in Job._meta.indexes if i.name == "job_filler_true_idx"), None)

    assert index is not None
    assert index.fields == ["created"]
    assert index.condition == models.Q(filler=True)


def test_update_fields_moves_the_updated_timestamp():
    """A status change through update_fields is a change, so updated must move."""
    author = User.objects.create_user(username="updated-test-author-1")
    job = Job.objects.create(author=author, status=Job.QUEUED)
    before = job.updated

    job.update_fields({"status": Job.RUNNING})

    assert job.updated > before
    assert Job.objects.get(pk=job.pk).updated == job.updated


def test_save_direct_moves_the_updated_timestamp():
    """save_direct bypasses save(), so it has to stamp updated itself."""
    author = User.objects.create_user(username="updated-test-author-2")
    job = Job.objects.create(author=author, status=Job.QUEUED)
    before = job.updated

    job.status = Job.RUNNING
    job.save_direct(["status"])

    assert job.updated > before
    assert Job.objects.get(pk=job.pk).updated == job.updated


class TestChangeStatus:
    """Unit tests for Job.change_status()."""

    def test_persists_status_and_job_fields(self):
        author = User.objects.create_user(username="change-status-author-1")
        job = Job.objects.create(author=author, status=Job.QUEUED)

        job.change_status(
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.UPDATE_JOB_STATUS,
            status=Job.RUNNING,
            job_fields={"sub_status": "mapping"},
        )

        job.refresh_from_db()
        assert job.status == Job.RUNNING
        assert job.sub_status == "mapping"

    def test_creates_the_status_change_event(self):
        author = User.objects.create_user(username="change-status-author-2")
        job = Job.objects.create(author=author, status=Job.RUNNING)

        event = job.change_status(
            origin=JobEventOrigin.API,
            context=JobEventContext.STOP_JOB,
            status=Job.STOPPED,
        )

        assert event.data == {"status": Job.STOPPED}
        assert event.origin == JobEventOrigin.API
        assert event.context == JobEventContext.STOP_JOB

    def test_rolls_back_the_event_if_the_job_write_fails(self, monkeypatch):
        """Event-then-job must be all-or-nothing: a failed job write must not leave
        a JobEvent behind with no matching state change."""
        author = User.objects.create_user(username="change-status-author-3")
        job = Job.objects.create(author=author, status=Job.QUEUED)

        def _boom(self, fields_map):  # pylint: disable=unused-argument
            raise RuntimeError("boom")

        monkeypatch.setattr(Job, "update_fields", _boom)

        with pytest.raises(RuntimeError, match="boom"):
            job.change_status(
                origin=JobEventOrigin.SCHEDULER,
                context=JobEventContext.UPDATE_JOB_STATUS,
                status=Job.RUNNING,
            )

        assert JobEvent.objects.filter(job=job).count() == 0


class TestChangeStatusOutboxRow:
    """Job.change_status() keeping the JobOutbox row in step with the job."""

    def _transition(self, job, status):
        return job.change_status(
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.UPDATE_JOB_STATUS,
            status=status,
        )

    def test_does_nothing_when_the_job_has_no_outbox_row(self):
        """Filler jobs, Ray jobs and pre-deployment jobs have no row: the update matches nothing."""
        author = User.objects.create_user(username="outbox-author-1")
        job = Job.objects.create(author=author, runner=Program.FLEETS, status=Job.QUEUED, filler=True)

        self._transition(job, Job.RUNNING)

        assert JobOutbox.objects.count() == 0

    def test_copies_the_status_and_takes_the_timestamp_from_the_event(self):
        job, _ = _job_with_outbox("outbox-author-2")

        event = self._transition(job, Job.PENDING)

        row = JobOutbox.objects.get(job=job)
        assert row.job_status == Job.PENDING
        assert row.status_changed_at == event.created

    def test_sets_has_run_on_running_and_never_back_to_false(self):
        job, _ = _job_with_outbox("outbox-author-3", status=Job.PENDING)

        self._transition(job, Job.RUNNING)
        assert JobOutbox.objects.get(job=job).has_run is True

        self._transition(job, Job.SUCCEEDED)
        assert JobOutbox.objects.get(job=job).has_run is True

    def test_sets_has_run_on_succeeded_with_no_running_event(self):
        """A job fast enough to fit between two scheduler polls is never seen RUNNING."""
        job, _ = _job_with_outbox("outbox-author-4", status=Job.PENDING)

        self._transition(job, Job.SUCCEEDED)

        assert JobOutbox.objects.get(job=job).has_run is True

    def test_does_not_set_has_run_on_a_terminal_status_other_than_succeeded(self):
        """FAILED and STOPPED prove nothing: the job may never have started."""
        job, _ = _job_with_outbox("outbox-author-5", status=Job.PENDING)

        self._transition(job, Job.STOPPED)

        assert JobOutbox.objects.get(job=job).has_run is False

    def test_does_not_set_has_run_on_pending(self):
        job, _ = _job_with_outbox("outbox-author-6")

        self._transition(job, Job.PENDING)

        assert JobOutbox.objects.get(job=job).has_run is False

    def test_does_not_touch_the_sent_markers(self):
        """Clearing a sent marker would send the same billing fact twice."""
        sent = timezone.now() - timedelta(minutes=5)
        job, _ = _job_with_outbox(
            "outbox-author-7",
            status=Job.RUNNING,
            has_run=True,
            license_fee_sent_at=sent,
            billing_sent_at=sent,
        )

        self._transition(job, Job.SUCCEEDED)

        row = JobOutbox.objects.get(job=job)
        assert row.license_fee_sent_at == sent
        assert row.billing_sent_at == sent
