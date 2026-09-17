"""Unit tests for JobOutboxQuerySet."""

from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from core.models import Job, JobOutbox, Program

pytestmark = pytest.mark.django_db


def _make_job(user, status=Job.QUEUED):
    return Job.objects.create(author=user, runner=Program.FLEETS, status=status)


def _make_outbox(
    job,
    job_status=Job.QUEUED,
    has_run=False,
    license_fee_required=True,
    license_fee_sent_at=None,
    billing_sent_at=None,
    status_changed_at=None,
):
    return JobOutbox.objects.create(
        job=job,
        job_status=job_status,
        status_changed_at=status_changed_at or timezone.now(),
        has_run=has_run,
        license_fee_required=license_fee_required,
        license_fee_sent_at=license_fee_sent_at,
        billing_sent_at=billing_sent_at,
    )


@pytest.fixture
def user():
    return User.objects.create_user(username="author")


class TestPendingLicenseFee:
    def test_pending_once_has_run(self, user):
        job = _make_job(user, status=Job.RUNNING)
        row = _make_outbox(job, job_status=Job.RUNNING, has_run=True, license_fee_required=True)

        assert row in JobOutbox.objects.pending_license_fee()

    def test_pending_when_succeeded_without_having_run(self, user):
        job = _make_job(user, status=Job.SUCCEEDED)
        row = _make_outbox(job, job_status=Job.SUCCEEDED, has_run=False, license_fee_required=True)

        assert row in JobOutbox.objects.pending_license_fee()

    def test_not_pending_when_cancelled_before_running(self, user):
        job = _make_job(user, status=Job.STOPPED)
        row = _make_outbox(job, job_status=Job.STOPPED, has_run=False, license_fee_required=True)

        assert row not in JobOutbox.objects.pending_license_fee()

    def test_not_pending_when_not_required(self, user):
        job = _make_job(user, status=Job.RUNNING)
        row = _make_outbox(job, job_status=Job.RUNNING, has_run=True, license_fee_required=False)

        assert row not in JobOutbox.objects.pending_license_fee()

    def test_not_pending_once_sent(self, user):
        job = _make_job(user, status=Job.RUNNING)
        row = _make_outbox(
            job,
            job_status=Job.RUNNING,
            has_run=True,
            license_fee_required=True,
            license_fee_sent_at=timezone.now(),
        )

        assert row not in JobOutbox.objects.pending_license_fee()


class TestPendingBillingEvent:
    def test_pending_when_terminal_and_unsent(self, user):
        job = _make_job(user, status=Job.SUCCEEDED)
        row = _make_outbox(job, job_status=Job.SUCCEEDED)

        assert row in JobOutbox.objects.pending_billing_event()

    def test_not_pending_when_not_terminal(self, user):
        job = _make_job(user, status=Job.RUNNING)
        row = _make_outbox(job, job_status=Job.RUNNING)

        assert row not in JobOutbox.objects.pending_billing_event()

    def test_not_pending_once_sent(self, user):
        job = _make_job(user, status=Job.SUCCEEDED)
        row = _make_outbox(job, job_status=Job.SUCCEEDED, billing_sent_at=timezone.now())

        assert row not in JobOutbox.objects.pending_billing_event()


class TestPendingKafkaOutbox:
    def test_orders_oldest_first(self, user):
        older_job = _make_job(user, status=Job.SUCCEEDED)
        newer_job = _make_job(user, status=Job.SUCCEEDED)
        now = timezone.now()
        newer = _make_outbox(newer_job, job_status=Job.SUCCEEDED, status_changed_at=now)
        older = _make_outbox(older_job, job_status=Job.SUCCEEDED, status_changed_at=now - timedelta(hours=1))

        result = list(JobOutbox.objects.pending_kafka_outbox(limit=10))

        assert result == [older, newer]

    def test_respects_the_limit(self, user):
        for _ in range(3):
            job = _make_job(user, status=Job.SUCCEEDED)
            _make_outbox(job, job_status=Job.SUCCEEDED)

        assert len(list(JobOutbox.objects.pending_kafka_outbox(limit=2))) == 2


class TestReadyToDelete:
    def test_not_ready_while_queued_even_if_license_fee_not_required(self, user):
        """A freshly created row must not read as vacuously settled before the job runs."""
        job = _make_job(user, status=Job.QUEUED)
        row = _make_outbox(job, job_status=Job.QUEUED, has_run=False, license_fee_required=False)

        assert row not in JobOutbox.objects.ready_to_delete()

    def test_not_ready_while_running_with_no_license_fee_required(self, user):
        job = _make_job(user, status=Job.RUNNING)
        row = _make_outbox(job, job_status=Job.RUNNING, has_run=True, license_fee_required=False)

        assert row not in JobOutbox.objects.ready_to_delete()

    def test_ready_when_terminal_cancelled_before_running_and_billing_sent(self, user):
        job = _make_job(user, status=Job.STOPPED)
        row = _make_outbox(
            job,
            job_status=Job.STOPPED,
            has_run=False,
            license_fee_required=True,
            billing_sent_at=timezone.now(),
        )

        assert row in JobOutbox.objects.ready_to_delete()

    def test_not_ready_when_terminal_but_billing_event_unsent(self, user):
        job = _make_job(user, status=Job.SUCCEEDED)
        row = _make_outbox(
            job,
            job_status=Job.SUCCEEDED,
            has_run=True,
            license_fee_required=True,
            license_fee_sent_at=timezone.now(),
            billing_sent_at=None,
        )

        assert row not in JobOutbox.objects.ready_to_delete()

    def test_ready_when_terminal_and_both_facts_sent(self, user):
        job = _make_job(user, status=Job.SUCCEEDED)
        row = _make_outbox(
            job,
            job_status=Job.SUCCEEDED,
            has_run=True,
            license_fee_required=True,
            license_fee_sent_at=timezone.now(),
            billing_sent_at=timezone.now(),
        )

        assert row in JobOutbox.objects.ready_to_delete()


class TestCascadeDelete:
    def test_deleting_the_job_deletes_its_outbox_row(self, user):
        job = _make_job(user, status=Job.QUEUED)
        _make_outbox(job, job_status=Job.QUEUED)

        job.delete()

        assert JobOutbox.objects.count() == 0
