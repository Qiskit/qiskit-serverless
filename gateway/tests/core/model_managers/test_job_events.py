"""Unit tests for JobEventQuerySet.

The outbox row that mirrors a status event is written by JobTransitionService, so those
tests live in tests/core/services/test_job_transitions.py.
"""

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


class TestAddStatusEvent:
    """Unit tests for JobEventQuerySet.add_status_event()."""

    def test_extra_data_is_merged_alongside_status(self, job):
        event = JobEvent.objects.add_status_event(
            job_id=job.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.PROGRAM_TIMEOUT_STOP,
            status=Job.STOPPED,
            extra_data={"timeout_hours": 24},
        )

        assert event.data == {"status": Job.STOPPED, "timeout_hours": 24}


class TestGetJobEvents:
    """Unit tests for JobEventQuerySet.get_job_events()."""

    def test_filters_by_type_and_context(self, job):
        _add_status_event(job, Job.RUNNING)
        timeout_event = JobEvent.objects.add_status_event(
            job_id=job.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.PROGRAM_TIMEOUT_STOP,
            status=Job.STOPPED,
            extra_data={"timeout_hours": 24},
        )

        events = JobEvent.objects.get_job_events(
            job.id, JobEventType.STATUS_CHANGE, JobEventContext.PROGRAM_TIMEOUT_STOP
        )

        assert list(events) == [timeout_event]

    def test_context_without_type_filters_across_event_types(self, job):
        event = JobEvent.objects.create(
            job_id=job.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.PROGRAM_TIMEOUT_STOP,
            event_type=JobEventType.ERROR,
            data={"code": "PROGRAM_TIMEOUT"},
        )
        _add_status_event(job, Job.RUNNING)

        events = JobEvent.objects.get_job_events(job.id, None, JobEventContext.PROGRAM_TIMEOUT_STOP)

        assert list(events) == [event]


class TestFirstTerminalAt:
    """Unit tests for JobEventQuerySet.first_terminal_at()."""

    def test_returns_none_when_the_job_never_finished(self, job):
        _add_status_event(job, Job.RUNNING)

        assert JobEvent.objects.first_terminal_at(job.id) is None

    def test_returns_the_created_timestamp_of_the_terminal_event(self, job):
        _add_status_event(job, Job.RUNNING)
        event = _add_status_event(job, Job.SUCCEEDED)

        assert JobEvent.objects.first_terminal_at(job.id) == event.created

    def test_ignores_non_terminal_status_events(self, job):
        _add_status_event(job, Job.PENDING)
        _add_status_event(job, Job.STOPPING)

        assert JobEvent.objects.first_terminal_at(job.id) is None


class TestHasBillingEvent:
    """Unit tests for JobEventQuerySet.has_billing_event()."""

    def test_returns_false_when_the_job_has_no_billing_event(self, job):
        _add_status_event(job, Job.RUNNING)

        assert JobEvent.objects.has_billing_event(job.id) is False

    def test_returns_true_when_the_job_has_a_billing_event(self, job):
        JobEvent.objects.create(
            job_id=job.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.UPDATE_JOB_STATUS,
            event_type=JobEventType.BILLING,
        )

        assert JobEvent.objects.has_billing_event(job.id) is True

    def test_ignores_the_billing_event_of_another_job(self, job, user):
        other = Job.objects.create(author=user, runner=Program.FLEETS, status=Job.QUEUED)
        JobEvent.objects.create(
            job_id=other.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.UPDATE_JOB_STATUS,
            event_type=JobEventType.BILLING,
        )

        assert JobEvent.objects.has_billing_event(job.id) is False
