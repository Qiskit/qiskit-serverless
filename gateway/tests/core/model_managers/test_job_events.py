"""Unit tests for JobEventQuerySet.

The outbox row that mirrors a status event is written by JobTransitionService, so those
tests live in tests/core/services/test_job_transitions.py.
"""

from datetime import datetime, timedelta, timezone

import pytest
from django.contrib.auth.models import User

from core.model_managers.job_events import JobEventContext, JobEventOrigin, JobEventType
from core.models import Job, JobEvent, Program

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


class TestAddStatusEvent:
    """Unit tests for JobEventQuerySet.add_status_event()."""

    def test_the_event_has_no_occurred_at_by_default(self, job):
        before = datetime.now(timezone.utc)

        event = _add_status_event(job, Job.RUNNING)

        assert before <= event.created <= datetime.now(timezone.utc)
        assert event.occurred_at is None
        assert event.happened_at == event.created

    def test_the_event_keeps_when_it_really_happened_apart_from_when_it_was_written(self, job):
        happened = datetime.now(timezone.utc) - timedelta(seconds=5)
        before = datetime.now(timezone.utc)

        event = JobEvent.objects.add_status_event(
            job_id=job.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.UPDATE_JOB_STATUS,
            status=Job.RUNNING,
            occurred_at=happened,
        )

        event.refresh_from_db()
        assert event.occurred_at == happened
        assert event.happened_at == happened
        assert before <= event.created <= datetime.now(timezone.utc)


class TestFirstRunningAt:
    """Unit tests for JobEventQuerySet.first_running_at()."""

    def test_returns_the_time_the_running_event_really_happened(self, job):
        happened = datetime.now(timezone.utc) - timedelta(seconds=5)
        JobEvent.objects.add_status_event(
            job_id=job.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.UPDATE_JOB_STATUS,
            status=Job.RUNNING,
            occurred_at=happened,
        )

        assert JobEvent.objects.first_running_at(job.id) == happened

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

    def test_orders_by_when_it_happened_not_by_when_it_was_written(self, job):
        """A retry can write a second running event that happened before the first one was written."""
        now = datetime.now(timezone.utc)
        _add_status_event(job, Job.RUNNING)
        earlier = now - timedelta(minutes=2)
        JobEvent.objects.add_status_event(
            job_id=job.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.UPDATE_JOB_STATUS,
            status=Job.RUNNING,
            occurred_at=earlier,
        )

        assert JobEvent.objects.first_running_at(job.id) == earlier

    def test_ignores_non_status_change_events_even_if_data_has_a_status_key(self, job):
        JobEvent.objects.create(
            job_id=job.id,
            origin=JobEventOrigin.API,
            context=JobEventContext.SEND_ERROR,
            event_type=JobEventType.ERROR,
            data={"status": Job.RUNNING},
        )

        assert JobEvent.objects.first_running_at(job.id) is None


class TestFirstTerminalAt:
    """Unit tests for JobEventQuerySet.first_terminal_at()."""

    def test_returns_none_when_the_job_never_finished(self, job):
        _add_status_event(job, Job.RUNNING)

        assert JobEvent.objects.first_terminal_at(job.id) is None

    def test_returns_the_created_timestamp_of_the_terminal_event(self, job):
        _add_status_event(job, Job.RUNNING)
        event = _add_status_event(job, Job.SUCCEEDED)

        assert JobEvent.objects.first_terminal_at(job.id) == event.created

    def test_returns_the_time_the_terminal_event_really_happened(self, job):
        happened = datetime.now(timezone.utc) - timedelta(seconds=5)
        JobEvent.objects.add_status_event(
            job_id=job.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.UPDATE_JOB_STATUS,
            status=Job.FAILED,
            occurred_at=happened,
        )

        assert JobEvent.objects.first_terminal_at(job.id) == happened

    def test_ignores_non_terminal_status_events(self, job):
        _add_status_event(job, Job.PENDING)
        _add_status_event(job, Job.STOPPING)

        assert JobEvent.objects.first_terminal_at(job.id) is None
