"""Unit tests for UpdateFleetsJobsStatuses."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from core.models import Job, Program
from core.services.runners import RunnerError
from scheduler.tasks.update_fleets_jobs_statuses import UpdateFleetsJobsStatuses

_MOD = "scheduler.tasks.update_fleets_jobs_statuses"


def _make_task():
    kill_signal = MagicMock()
    kill_signal.received = False
    return UpdateFleetsJobsStatuses(kill_signal=kill_signal, metrics=MagicMock())


def _make_fleets_job(status=Job.RUNNING, fleet_id="fleet-123"):
    job = MagicMock(spec=Job)
    job.runner = Program.FLEETS
    job.fleet_id = fleet_id
    job.status = status
    job.result = None
    job.logs = ""
    job.env_vars = "{}"
    job.sub_status = None
    job.in_terminal_state.return_value = status in Job.TERMINAL_STATUSES

    def _apply_update_fields(fields_map):
        for field, value in fields_map.items():
            setattr(job, field, value)

    job.update_fields = MagicMock(side_effect=_apply_update_fields)
    return job


class TestUpdateJobStatus:
    """Orchestration tests for update_job_status()."""

    def test_returns_false_when_no_fleet_id(self):
        task = _make_task()
        job = _make_fleets_job(fleet_id=None)

        with patch(f"{_MOD}.get_runner") as mock_get_runner:
            result = task.update_job_status(job)

        assert result is False
        mock_get_runner.assert_not_called()

    def test_runner_error_calls_to_terminal_failed_and_returns_false(self):
        task = _make_task()
        job = _make_fleets_job()

        mock_runner = MagicMock()
        mock_runner.status.side_effect = RunnerError("connection error")

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch.object(task, "to_terminal") as mock_terminal,
        ):
            result = task.update_job_status(job)

        mock_terminal.assert_called_once_with(job, Job.FAILED)
        assert result is False

    def test_succeeded_calls_to_terminal_records_duration_returns_true(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        mock_runner = MagicMock()
        mock_runner.status.return_value = Job.SUCCEEDED

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch.object(task, "to_terminal") as mock_terminal,
            patch.object(task, "_record_execution_duration") as mock_duration,
        ):
            result = task.update_job_status(job)

        mock_terminal.assert_called_once_with(job, Job.SUCCEEDED)
        mock_duration.assert_called_once_with(job)
        assert result is True

    def test_failed_calls_to_terminal_no_duration_returns_true(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        mock_runner = MagicMock()
        mock_runner.status.return_value = Job.FAILED

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch.object(task, "to_terminal"),
            patch.object(task, "_record_execution_duration") as mock_duration,
            patch.object(task, "_increment_terminal_counter"),
        ):
            result = task.update_job_status(job)

        mock_duration.assert_not_called()
        assert result is True

    def test_pending_to_running_calls_to_running_returns_true(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.PENDING)

        mock_runner = MagicMock()
        mock_runner.status.return_value = Job.RUNNING

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch.object(task, "to_running") as mock_running,
            patch.object(task, "stop_job_if_timeout"),
        ):
            result = task.update_job_status(job)

        mock_running.assert_called_once_with(job)
        assert result is True

    def test_running_to_running_skips_to_running_returns_true(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        mock_runner = MagicMock()
        mock_runner.status.return_value = Job.RUNNING

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch.object(task, "to_running") as mock_running,
            patch.object(task, "stop_job_if_timeout"),
        ):
            result = task.update_job_status(job)

        mock_running.assert_not_called()
        assert result is True

    def test_unknown_status_calls_to_terminal_failed(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        mock_runner = MagicMock()
        mock_runner.status.return_value = "UNKNOWN_STATUS"

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch.object(task, "to_terminal") as mock_terminal,
        ):
            result = task.update_job_status(job)

        mock_terminal.assert_called_once_with(job, Job.FAILED)
        assert result is True

    def test_stop_job_if_timeout_called_for_running(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        mock_runner = MagicMock()
        mock_runner.status.return_value = Job.RUNNING

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch.object(task, "stop_job_if_timeout") as mock_timeout,
        ):
            task.update_job_status(job)

        mock_timeout.assert_called_once_with(job)


class TestToTerminal:
    """Tests for to_terminal()."""

    def test_job_reaches_succeeded_state(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        with patch(f"{_MOD}.JobEvent"):
            task.to_terminal(job, Job.SUCCEEDED)

        assert job.status == Job.SUCCEEDED
        assert job.sub_status is None
        assert job.env_vars == "{}"

    def test_job_reaches_failed_state(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        with patch(f"{_MOD}.JobEvent"):
            task.to_terminal(job, Job.FAILED)

        assert job.status == Job.FAILED
        assert job.sub_status is None
        assert job.env_vars == "{}"


class TestToRunning:
    """Tests for to_running()."""

    def test_job_transitions_from_pending_to_running(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.PENDING)

        with patch(f"{_MOD}.JobEvent"):
            task.to_running(job)

        assert job.status == Job.RUNNING


class TestStopJobIfTimeout:
    """Tests for stop_job_if_timeout()."""

    def test_job_stopped_when_timeout_exceeded(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        past_event = MagicMock()
        past_event.created = datetime.now(timezone.utc) - timedelta(hours=100)

        with (
            patch(f"{_MOD}.settings") as mock_settings,
            patch(f"{_MOD}.JobEvent") as mock_event,
        ):
            mock_settings.PROGRAM_TIMEOUT = 1
            mock_event.objects.filter.return_value.order_by.return_value.first.return_value = past_event
            task.stop_job_if_timeout(job)

        assert job.status == Job.STOPPED
        assert job.sub_status is None
        task.metrics.increment_jobs_terminal.assert_called_once()

    def test_job_unchanged_when_within_timeout(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        recent_event = MagicMock()
        recent_event.created = datetime.now(timezone.utc) - timedelta(minutes=5)

        with (
            patch(f"{_MOD}.settings") as mock_settings,
            patch(f"{_MOD}.JobEvent") as mock_event,
        ):
            mock_settings.PROGRAM_TIMEOUT = 24
            mock_event.objects.filter.return_value.order_by.return_value.first.return_value = recent_event
            task.stop_job_if_timeout(job)

        assert job.status == Job.RUNNING
        job.update_fields.assert_not_called()


class TestRun:
    """Tests for run()."""

    def test_early_return_when_fleets_disabled(self):
        task = _make_task()

        with (
            patch(f"{_MOD}.settings") as mock_settings,
            patch(f"{_MOD}.Job") as mock_job_cls,
        ):
            mock_settings.LIMITS_MAX_FLEETS = 0
            task.run()

        mock_job_cls.objects.filter.assert_not_called()

    def test_kill_signal_stops_loop(self):
        task = _make_task()
        job1 = _make_fleets_job()
        job2 = _make_fleets_job()

        call_count = 0

        def fake_update(job):
            nonlocal call_count
            call_count += 1
            task.kill_signal.received = True
            return True

        with (
            patch(f"{_MOD}.settings") as mock_settings,
            patch(f"{_MOD}.Job") as mock_job_cls,
            patch.object(task, "update_job_status", side_effect=fake_update),
        ):
            mock_settings.LIMITS_MAX_FLEETS = 10
            mock_job_cls.objects.filter.return_value = [job1, job2]
            mock_job_cls.RUNNING_STATUSES = Job.RUNNING_STATUSES
            task.run()

        assert call_count == 1

    def test_logs_updated_count(self):
        task = _make_task()
        job1 = _make_fleets_job()
        job2 = _make_fleets_job()

        with (
            patch(f"{_MOD}.settings") as mock_settings,
            patch(f"{_MOD}.Job") as mock_job_cls,
            patch.object(task, "update_job_status", return_value=True),
            patch(f"{_MOD}.logger") as mock_logger,
        ):
            mock_settings.LIMITS_MAX_FLEETS = 10
            mock_job_cls.objects.filter.return_value = [job1, job2]
            mock_job_cls.RUNNING_STATUSES = Job.RUNNING_STATUSES
            task.run()

        mock_logger.info.assert_called_with("Updated %s Fleets jobs.", 2)
