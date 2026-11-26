"""Unit tests for ListJobEventsUseCase."""

import pytest
from django.contrib.auth.models import User

from api.use_cases.jobs.list_events import ListJobEventsUseCase
from core.model_managers.job_events import JobEventContext, JobEventOrigin, JobEventType
from core.models import Job, JobEvent, Program

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return User.objects.create_user(username="author")


@pytest.fixture
def job(user):
    return Job.objects.create(author=user, runner=Program.FLEETS, status=Job.QUEUED)


class TestListJobEventsUseCase:
    """Unit tests for ListJobEventsUseCase.execute()."""

    def test_context_filters_down_to_the_matching_status_change_event(self, user, job):
        JobEvent.objects.add_status_event(
            job_id=job.id, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS, status="RUNNING"
        )
        timeout_event = JobEvent.objects.add_status_event(
            job_id=job.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.PROGRAM_TIMEOUT_STOP,
            status="STOPPED",
            extra_data={"timeout_hours": 24},
        )

        events = ListJobEventsUseCase().execute(
            job.id, user, JobEventType.STATUS_CHANGE, JobEventContext.PROGRAM_TIMEOUT_STOP
        )

        assert events == [timeout_event]
        assert events[0].data == {"status": "STOPPED", "timeout_hours": 24}

    def test_without_context_returns_every_event_of_the_type(self, user, job):
        JobEvent.objects.add_status_event(
            job_id=job.id, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS, status="RUNNING"
        )
        JobEvent.objects.add_status_event(
            job_id=job.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.PROGRAM_TIMEOUT_STOP,
            status="STOPPED",
        )

        events = ListJobEventsUseCase().execute(job.id, user, JobEventType.STATUS_CHANGE)

        assert len(events) == 2
