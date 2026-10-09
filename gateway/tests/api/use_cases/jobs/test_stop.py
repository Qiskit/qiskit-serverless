"""Unit tests for StopJobUseCase."""

from unittest.mock import Mock, patch

import pytest
from django.contrib.auth.models import User

from api.domain.exceptions.engine_unavailable_exception import EngineUnavailableException
from api.use_cases.jobs.stop import StopJobUseCase, _CANCEL_DELAY_SECONDS, _CANCEL_RETRY_BUDGET_SECONDS
from core.ibm_cloud.clients import IAM_HTTP_TIMEOUT
from core.ibm_cloud.code_engine.fleets.handler import _CANCEL_TIMEOUT_SECONDS
from core.services.runners import RunnerError, RunnerRetryableError
from core.model_managers.job_events import JobEventOrigin
from core.models import Job, JobEvent, Program

# the use case builds the runner and hands it to try_stop, so one runner serves both attempts
_RUNNER = "api.use_cases.jobs.stop.get_runner"

pytestmark = pytest.mark.django_db


@pytest.fixture()
def author():
    return User.objects.create_user(username="stop-use-case-author")


def test_the_cancel_retry_fits_the_gunicorn_request_timeout():
    """A request gets 25s (charts/.../gateway/values.yaml), and the runtime job cancels still run
    after the fleet cancel. urllib3 retries a failed connect 4 times and does not retry a read on a
    POST, so a cancel costs 4x connect, not connect+read."""
    worst_cancel = max(4 * _CANCEL_TIMEOUT_SECONDS[0], sum(_CANCEL_TIMEOUT_SECONDS))
    worst_attempt = sum(IAM_HTTP_TIMEOUT) + worst_cancel

    # a second attempt only starts while the first is still inside the budget
    assert _CANCEL_RETRY_BUDGET_SECONDS + _CANCEL_DELAY_SECONDS + worst_attempt < 25


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

        with patch(_RUNNER, return_value=runner) as mock_get_runner:
            message = StopJobUseCase().execute(job.id, None, author)

        assert "Job is stopping." in message
        assert Job.objects.get(pk=job.pk).status == Job.STOPPING
        mock_get_runner.assert_called_once_with(job)
        # Once, not twice: the Ray cleanup must not send a second cancel for a Fleets job.
        runner.stop.assert_called_once_with()

    def test_a_fleet_that_is_gone_goes_straight_to_stopped(self, author):
        """Nothing will ever confirm a stop once Code Engine says the fleet is gone, so do not wait."""
        job = Job.objects.create(author=author, runner=Program.FLEETS, status=Job.RUNNING, fleet_id="fleet-gone")
        runner = Mock()
        runner.stop.return_value = False

        with patch(_RUNNER, return_value=runner):
            message = StopJobUseCase().execute(job.id, None, author)

        assert "Job has been stopped." in message
        assert Job.objects.get(pk=job.pk).status == Job.STOPPED

    def test_a_job_with_no_fleet_goes_straight_to_stopped(self, author):
        job = Job.objects.create(author=author, runner=Program.FLEETS, status=Job.QUEUED)

        with patch(_RUNNER) as mock_get_runner:
            message = StopJobUseCase().execute(job.id, None, author)

        assert "Job has been stopped." in message
        assert Job.objects.get(pk=job.pk).status == Job.STOPPED
        mock_get_runner.assert_not_called()

    @pytest.mark.parametrize(
        "error",
        [RunnerRetryableError("Too Many Requests"), RunnerError("Forbidden")],
        ids=["undeliverable", "refused"],
    )
    def test_a_cancel_that_did_not_land_is_retried_inside_the_request(self, author, error):
        """The API has its own gunicorn worker, so it can wait for a rate limit to clear. A 403 is
        retried too: it is usually an expired IAM cache."""
        job = Job.objects.create(author=author, runner=Program.FLEETS, status=Job.RUNNING, fleet_id="fleet-abc")
        runner = Mock()
        runner.stop.side_effect = [error, True]

        with (
            patch(_RUNNER, return_value=runner) as mock_get_runner,
            patch("api.use_cases.jobs.stop.time.sleep") as mock_sleep,
        ):
            message = StopJobUseCase().execute(job.id, None, author)

        assert "Job is stopping." in message
        assert Job.objects.get(pk=job.pk).status == Job.STOPPING
        assert runner.stop.call_count == 2
        mock_sleep.assert_called_once_with(_CANCEL_DELAY_SECONDS)
        # one runner for both attempts, so a Code Engine failure does not pay for a second IAM token
        mock_get_runner.assert_called_once_with(job)

    def test_a_cancel_that_failed_slowly_is_not_retried(self, author):
        """A slow failure has already eaten the request budget, so a second attempt would be killed
        mid-flight. The fast failures this retry exists for come back in milliseconds."""
        job = Job.objects.create(author=author, runner=Program.FLEETS, status=Job.RUNNING, fleet_id="fleet-abc")
        runner = Mock()
        runner.stop.side_effect = RunnerRetryableError("read timed out")
        clock = iter([0.0, _CANCEL_RETRY_BUDGET_SECONDS + 1])

        with (
            patch(_RUNNER, return_value=runner),
            patch("api.use_cases.jobs.stop.time.monotonic", side_effect=lambda: next(clock)),
            patch("api.use_cases.jobs.stop.time.sleep") as mock_sleep,
        ):
            with pytest.raises(EngineUnavailableException):
                StopJobUseCase().execute(job.id, None, author)

        assert runner.stop.call_count == 1
        mock_sleep.assert_not_called()

    def test_an_unusable_project_does_not_tell_the_user_to_retry(self, author):
        """No retry fixes a project an operator deactivated, so the message must not suggest one."""
        job = Job.objects.create(author=author, runner=Program.FLEETS, status=Job.RUNNING, fleet_id="fleet-abc")
        runner = Mock()
        runner.stop.side_effect = RunnerError("Code Engine project 'p' is not active")

        with (
            patch(_RUNNER, return_value=runner),
            patch("api.use_cases.jobs.stop.time.sleep"),
        ):
            with pytest.raises(EngineUnavailableException) as caught:
                StopJobUseCase().execute(job.id, None, author)

        assert "please retry" not in str(caught.value).lower()
        assert Job.objects.get(pk=job.pk).status == Job.RUNNING

    def test_a_cancel_that_never_gets_through_fails_the_request(self, author):
        """Two attempts, then 503."""
        job = Job.objects.create(author=author, runner=Program.FLEETS, status=Job.RUNNING, fleet_id="fleet-abc")
        runner = Mock()
        runner.stop.side_effect = RunnerRetryableError("Too Many Requests")

        with (
            patch(_RUNNER, return_value=runner),
            patch("api.use_cases.jobs.stop.time.sleep"),
        ):
            with pytest.raises(EngineUnavailableException):
                StopJobUseCase().execute(job.id, None, author)

        assert Job.objects.get(pk=job.pk).status == Job.RUNNING
        assert runner.stop.call_count == 2
        assert JobEvent.objects.filter(job=job).count() == 0

    def test_a_second_stop_sends_no_cancel_and_writes_no_event(self, author):
        """Already stopping: no cancel is sent and no event is written."""
        job = Job.objects.create(author=author, runner=Program.FLEETS, status=Job.STOPPING, fleet_id="fleet-abc")

        with patch(_RUNNER) as mock_get_runner:
            message = StopJobUseCase().execute(job.id, None, author)

        assert "Job is already stopping." in message
        assert Job.objects.get(pk=job.pk).status == Job.STOPPING
        assert JobEvent.objects.filter(job=job).count() == 0
        mock_get_runner.assert_not_called()

    def test_a_second_stop_still_cancels_the_runtime_jobs(self, author):
        """A stop the scheduler started cancels the fleet and nothing else, so a user's stop on a
        STOPPING row is the only thing that reaches their runtime jobs."""
        job = Job.objects.create(author=author, runner=Program.FLEETS, status=Job.STOPPING, fleet_id="fleet-abc")

        with patch(_RUNNER) as mock_get_runner:
            message = StopJobUseCase().execute(job.id, None, author)

        assert "Job is already stopping." in message
        # only _cancel_runtime_jobs says this, so it is what proves the path was taken
        assert "QiskitRuntimeService not found, cannot stop runtime jobs." in message
        mock_get_runner.assert_not_called()

    def test_a_concurrent_stop_reports_stopping_not_terminal(self, author):
        """Two gunicorn workers can both read the row as RUNNING. The loser's transition is refused,
        and STOPPING is not terminal, so it must not be reported as such."""
        job = Job.objects.create(author=author, runner=Program.FLEETS, status=Job.RUNNING, fleet_id="fleet-abc")
        runner = Mock()
        runner.stop.return_value = True

        def _win_the_race(*_args, **_kwargs):
            # Stand in for the other worker committing STOPPING between our read and our transition.
            Job.objects.filter(pk=job.pk).update(status=Job.STOPPING)
            return True

        runner.stop.side_effect = _win_the_race
        with patch(_RUNNER, return_value=runner):
            message = StopJobUseCase().execute(job.id, None, author)

        assert "Job is stopping." in message
        assert "terminal" not in message
        assert Job.objects.get(pk=job.pk).status == Job.STOPPING

    def test_a_concurrent_stop_that_lost_to_stopped_reports_stopped(self, author):
        """The writer that beat us can be the scheduler timeout, which never cancels the runtime jobs,
        so this request still has to run that block rather than answer "already terminal"."""
        job = Job.objects.create(author=author, runner=Program.FLEETS, status=Job.RUNNING, fleet_id="fleet-abc")
        runner = Mock()

        def _win_the_race(*_args, **_kwargs):
            Job.objects.filter(pk=job.pk).update(status=Job.STOPPED)
            return True

        runner.stop.side_effect = _win_the_race
        with patch(_RUNNER, return_value=runner):
            message = StopJobUseCase().execute(job.id, None, author)

        assert "Job has been stopped." in message
        assert "terminal" not in message
        assert Job.objects.get(pk=job.pk).status == Job.STOPPED

    def test_a_terminal_fleets_job_sends_no_cancel(self, author):
        """try_stop is never reached, so Code Engine is not called for a job that already ended."""
        job = Job.objects.create(author=author, runner=Program.FLEETS, status=Job.SUCCEEDED, fleet_id="fleet-abc")

        with patch(_RUNNER) as mock_get_runner:
            message = StopJobUseCase().execute(job.id, None, author)

        assert "Job already in terminal state." in message
        assert Job.objects.get(pk=job.pk).status == Job.SUCCEEDED
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
