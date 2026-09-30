"""Unit tests for StopJobUseCase."""

import pytest
from django.contrib.auth.models import User

from api.use_cases.jobs.stop import StopJobUseCase
from core.model_managers.job_events import JobEventOrigin
from core.models import Job, JobEvent, Program

pytestmark = pytest.mark.django_db


@pytest.fixture()
def author():
    return User.objects.create_user(username="stop-use-case-author")


class TestStopJobUseCase:
    def test_stop_job_reports_stopped(self, author):
        job = Job.objects.create(author=author, runner=Program.RAY, status=Job.QUEUED)

        message = StopJobUseCase().execute(job.id, None, author)

        assert "Job has been stopped." in message
        assert Job.objects.get(pk=job.pk).status == Job.STOPPED

    def test_stop_job_already_terminal_reports_that_instead(self, author):
        job = Job.objects.create(author=author, runner=Program.RAY, status=Job.SUCCEEDED)

        message = StopJobUseCase().execute(job.id, None, author)

        assert "Job already in terminal state." in message
        assert Job.objects.get(pk=job.pk).status == Job.SUCCEEDED

    def test_stop_job_that_turned_terminal_since_the_read_reports_that_instead(self, author, monkeypatch):
        """in_terminal_state() reflects a stale in-memory read; the transition re-reads the row
        under a lock and no-ops if it is already terminal there, so this must not be reported
        as stopped, and must not create a second JobEvent."""
        job = Job.objects.create(author=author, runner=Program.RAY, status=Job.SUCCEEDED)
        monkeypatch.setattr(Job, "in_terminal_state", lambda self: False)

        message = StopJobUseCase().execute(job.id, None, author)

        assert "Job already in terminal state." in message
        assert Job.objects.get(pk=job.pk).status == Job.SUCCEEDED
        assert JobEvent.objects.filter(job=job).count() == 0

    def test_stop_job_creates_a_status_change_event(self, author):
        job = Job.objects.create(author=author, runner=Program.RAY, status=Job.QUEUED)

        StopJobUseCase().execute(job.id, None, author)

        event = JobEvent.objects.get(job=job)
        assert event.data == {"status": Job.STOPPED}
        assert event.origin == JobEventOrigin.API
