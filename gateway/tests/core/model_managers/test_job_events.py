"""Unit tests for JobEventQuerySet.

The outbox row that mirrors a status event is written by Job.change_status, so those
tests live in tests/core/test_job_model.py.
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
