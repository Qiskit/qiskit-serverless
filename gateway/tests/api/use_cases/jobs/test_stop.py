"""Unit tests for StopJobUseCase."""

from unittest.mock import Mock, patch

import pytest
from django.contrib.auth.models import User

from api.domain.exceptions.engine_unavailable_exception import EngineUnavailableException
from api.use_cases.jobs.stop import StopJobUseCase
from core.services.runners import RunnerError
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


class TestStopFleetsJob:
    """A Fleets stop sends the cancel in the request. STOPPING means Code Engine accepted it."""

    def test_an_accepted_cancel_reports_stopping(self, author):
        job = Job.objects.create(author=author, runner=Program.FLEETS, status=Job.RUNNING, fleet_id="fleet-abc")
        runner = Mock()
        runner.stop.return_value = True

        with patch("api.use_cases.jobs.stop.get_runner", return_value=runner) as mock_get_runner:
            message = StopJobUseCase().execute(job.id, None, author)

        assert "Job is stopping." in message
        assert Job.objects.get(pk=job.pk).status == Job.STOPPING
        mock_get_runner.assert_called_once_with(job)
        runner.stop.assert_called_once_with()

    def test_a_fleet_that_is_gone_goes_straight_to_stopped(self):
        """stop() returns False only for a 404, so nothing will ever confirm a stop. No point waiting."""
        author = User.objects.create_user(username="gone-fleet-author")
        job = Job.objects.create(author=author, runner=Program.FLEETS, status=Job.RUNNING, fleet_id="fleet-gone")
        runner = Mock()
        runner.stop.return_value = False

        with patch("api.use_cases.jobs.stop.get_runner", return_value=runner):
            message = StopJobUseCase().execute(job.id, None, author)

        assert "Job has been stopped." in message
        assert Job.objects.get(pk=job.pk).status == Job.STOPPED

    def test_a_job_with_no_fleet_goes_straight_to_stopped(self, author):
        job = Job.objects.create(author=author, runner=Program.FLEETS, status=Job.QUEUED)

        with patch("api.use_cases.jobs.stop.get_runner") as mock_get_runner:
            message = StopJobUseCase().execute(job.id, None, author)

        assert "Job has been stopped." in message
        assert Job.objects.get(pk=job.pk).status == Job.STOPPED
        mock_get_runner.assert_not_called()

    def test_a_cancel_that_cannot_be_delivered_fails_the_request(self, author):
        """The job stays RUNNING so the user can retry. A STOPPING row would claim a cancel we never sent."""
        job = Job.objects.create(author=author, runner=Program.FLEETS, status=Job.RUNNING, fleet_id="fleet-abc")
        runner = Mock()
        runner.stop.side_effect = RunnerError("Code Engine rate limited the cancel")

        with patch("api.use_cases.jobs.stop.get_runner", return_value=runner):
            with pytest.raises(EngineUnavailableException):
                StopJobUseCase().execute(job.id, None, author)

        assert Job.objects.get(pk=job.pk).status == Job.RUNNING
        assert JobEvent.objects.filter(job=job).count() == 0

    def test_a_second_stop_sends_no_cancel_and_writes_no_event(self, author):
        """The deadline is read from the STOPPING event, so a second one must not be written."""
        job = Job.objects.create(author=author, runner=Program.FLEETS, status=Job.STOPPING, fleet_id="fleet-abc")

        with patch("api.use_cases.jobs.stop.get_runner") as mock_get_runner:
            message = StopJobUseCase().execute(job.id, None, author)

        assert "Job is already stopping." in message
        assert Job.objects.get(pk=job.pk).status == Job.STOPPING
        assert JobEvent.objects.filter(job=job).count() == 0
        mock_get_runner.assert_not_called()

    def test_a_ray_job_never_reaches_stopping(self, author):
        """The fork at this writer is the only guard: the Ray poller does not consult VALID_TRANSITIONS.

        The fleet_id matters. Without one both branches converge on STOPPED and the fork goes unpinned.
        """
        job = Job.objects.create(author=author, runner=Program.RAY, status=Job.RUNNING, fleet_id="fleet-abc")

        with patch("api.use_cases.jobs.stop.get_runner"):
            message = StopJobUseCase().execute(job.id, None, author)

        assert "Job has been stopped." in message
        assert Job.objects.get(pk=job.pk).status == Job.STOPPED
