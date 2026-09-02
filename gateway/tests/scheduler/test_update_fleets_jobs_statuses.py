"""Unit tests for UpdateFleetsJobsStatuses."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from core.model_managers.job_events import JobEventContext, JobEventOrigin
from core.models import Job, Program
from core.services.runners import RunnerError
from scheduler.tasks.update_fleets_jobs_statuses import UpdateFleetsJobsStatuses
from tests.utils import TestUtils

_MOD = "scheduler.tasks.update_fleets_jobs_statuses"


def _make_task():
    kill_signal = MagicMock()
    kill_signal.received = False
    task = UpdateFleetsJobsStatuses.__new__(UpdateFleetsJobsStatuses)
    task.kill_signal = kill_signal
    task.metrics = MagicMock()
    task._event_streams_client = MagicMock()
    return task


def _make_fleets_job(status=Job.RUNNING, fleet_id="fleet-123"):
    job = MagicMock(spec=Job)
    job.runner = Program.FLEETS
    job.fleet_id = fleet_id
    job.status = status
    job.result = None
    job.logs = ""
    job.env_vars = "{}"
    job.sub_status = None
    job.running_started_at = None
    job.instance_crn = "crn:v1:bluemix:public:quantum-computing:us-east:a/abc:def::"
    job.filler = False
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

    def test_runner_error_leaves_the_status_alone_and_checks_the_timeout(self):
        task = _make_task()
        job = _make_fleets_job()

        mock_runner = MagicMock()
        mock_runner.status.side_effect = RunnerError("Code Engine project 'p' is not active")

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch.object(task, "to_terminal") as mock_terminal,
            patch.object(task, "stop_job_if_timeout") as mock_timeout,
        ):
            result = task.update_job_status(job)

        mock_terminal.assert_not_called()
        mock_timeout.assert_called_once_with(job)
        assert result is False

    def test_succeeded_calls_to_terminal_and_records_duration(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        mock_runner = MagicMock()
        mock_runner.status.return_value = Job.SUCCEEDED

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch.object(task, "to_terminal") as mock_terminal,
            patch.object(task, "_record_execution_duration") as mock_duration,
        ):
            task.update_job_status(job)

        mock_terminal.assert_called_once_with(job, Job.SUCCEEDED)
        mock_duration.assert_called_once_with(job)

    def test_pending_to_running_calls_to_running(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.PENDING)

        mock_runner = MagicMock()
        mock_runner.status.return_value = Job.RUNNING

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch.object(task, "to_running") as mock_running,
            patch.object(task, "stop_job_if_timeout"),
        ):
            task.update_job_status(job)

        mock_running.assert_called_once_with(job)

    def test_running_to_running_skips_to_running(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        mock_runner = MagicMock()
        mock_runner.status.return_value = Job.RUNNING

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch.object(task, "to_running") as mock_running,
            patch.object(task, "stop_job_if_timeout"),
        ):
            task.update_job_status(job)

        mock_running.assert_not_called()

    def test_none_status_skips_update_and_returns_false(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        mock_runner = MagicMock()
        mock_runner.status.return_value = None

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch.object(task, "stop_job_if_timeout"),
            patch.object(task, "to_terminal") as mock_terminal,
            patch.object(task, "to_running") as mock_running,
        ):
            result = task.update_job_status(job)

        assert result is False
        mock_terminal.assert_not_called()
        mock_running.assert_not_called()
        assert job.status == Job.RUNNING

    def test_none_status_preserves_pending_state(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.PENDING)

        mock_runner = MagicMock()
        mock_runner.status.return_value = None

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch.object(task, "stop_job_if_timeout"),
            patch.object(task, "to_terminal") as mock_terminal,
        ):
            result = task.update_job_status(job)

        assert result is False
        mock_terminal.assert_not_called()
        assert job.status == Job.PENDING

    def test_none_status_still_checks_the_timeout(self):
        """A job whose status never resolves must still be bounded.

        Nothing else in the scheduler touches a PENDING or RUNNING Fleets job, so
        without this the job holds the user's concurrency slot forever. This is the
        regression guard for that.
        """
        task = _make_task()
        job = _make_fleets_job(status=Job.PENDING)

        mock_runner = MagicMock()
        mock_runner.status.return_value = None

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch.object(task, "stop_job_if_timeout") as mock_timeout,
        ):
            task.update_job_status(job)

        mock_timeout.assert_called_once_with(job)

    def test_unknown_status_calls_to_terminal_failed(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        mock_runner = MagicMock()
        mock_runner.status.return_value = "UNKNOWN_STATUS"

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch.object(task, "to_terminal") as mock_terminal,
        ):
            task.update_job_status(job)

        mock_terminal.assert_called_once_with(job, Job.FAILED)


class TestToTerminal:
    """Tests for to_terminal()."""

    def test_job_reaches_succeeded_state(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)
        job.sub_status = "pending"
        job.env_vars = '{"key": "value"}'

        with patch(f"{_MOD}.JobEvent") as mock_job_event:
            task.to_terminal(job, Job.SUCCEEDED)

        assert job.status == Job.SUCCEEDED
        assert job.sub_status is None
        assert job.env_vars == "{}"
        mock_job_event.objects.add_status_event.assert_called_once_with(
            job_id=job.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.UPDATE_JOB_STATUS,
            status=Job.SUCCEEDED,
        )

    def test_job_reaches_failed_state(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)
        job.sub_status = "pending"
        job.env_vars = '{"key": "value"}'

        with patch(f"{_MOD}.JobEvent") as mock_job_event:
            task.to_terminal(job, Job.FAILED)

        assert job.status == Job.FAILED
        assert job.sub_status is None
        assert job.env_vars == "{}"
        mock_job_event.objects.add_status_event.assert_called_once_with(
            job_id=job.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.UPDATE_JOB_STATUS,
            status=Job.FAILED,
        )


class TestToRunning:
    """Tests for to_running()."""

    def test_job_transitions_from_pending_to_running(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.PENDING)

        with patch(f"{_MOD}.JobEvent") as mock_job_event:
            task.to_running(job)

        assert job.status == Job.RUNNING
        mock_job_event.objects.add_status_event.assert_called_once_with(
            job_id=job.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.UPDATE_JOB_STATUS,
            status=Job.RUNNING,
        )

    def test_to_running_sets_running_started_at(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.PENDING)

        with (
            patch(f"{_MOD}.JobEvent"),
            patch(f"{_MOD}.django_timezone") as mock_dt,
        ):
            fake_now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
            mock_dt.now.return_value = fake_now
            task.to_running(job)

        job.update_fields.assert_called_once_with(
            {
                "status": Job.RUNNING,
                "running_started_at": fake_now,
            }
        )


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


class TestEventStreamsIntegration:
    """Tests that emit methods are called at the right lifecycle points."""

    def test_to_running_emits_job_started_before_db_update(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.PENDING)

        call_order = []
        task.event_streams_client.emit_job_started.side_effect = lambda j: call_order.append("publish")
        job.update_fields = MagicMock(side_effect=lambda f: call_order.append("db"))

        with patch(f"{_MOD}.JobEvent"):
            with patch(f"{_MOD}.django_timezone"):
                task.to_running(job)

        assert call_order == ["publish", "db"]
        task.event_streams_client.emit_job_started.assert_called_once_with(job)

    def test_to_running_raises_if_publish_fails(self):
        task = _make_task()
        task.event_streams_client.emit_job_started.side_effect = Exception("broker down")
        job = _make_fleets_job(status=Job.PENDING)

        with patch(f"{_MOD}.JobEvent"):
            with patch(f"{_MOD}.django_timezone"):
                with pytest.raises(Exception, match="broker down"):
                    task.to_running(job)

        job.update_fields.assert_not_called()

    def test_to_terminal_emits_job_completed_before_db_update(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        call_order = []
        task.event_streams_client.emit_job_completed.side_effect = lambda j: call_order.append("publish")
        job.update_fields = MagicMock(side_effect=lambda f: call_order.append("db"))

        with patch(f"{_MOD}.JobEvent"):
            task.to_terminal(job, Job.SUCCEEDED)

        assert call_order == ["publish", "db"]
        task.event_streams_client.emit_job_completed.assert_called_once_with(job)

    def test_to_terminal_raises_if_publish_fails(self):
        task = _make_task()
        task.event_streams_client.emit_job_completed.side_effect = Exception("broker down")
        job = _make_fleets_job(status=Job.RUNNING)

        with patch(f"{_MOD}.JobEvent"):
            with pytest.raises(Exception, match="broker down"):
                task.to_terminal(job, Job.SUCCEEDED)

        job.update_fields.assert_not_called()

    def test_update_job_status_emits_job_in_progress_for_running_job(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        mock_runner = MagicMock()
        mock_runner.status.return_value = Job.RUNNING

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch.object(task, "stop_job_if_timeout"),
        ):
            task.update_job_status(job)

        task.event_streams_client.emit_job_in_progress.assert_called_once_with(job)

    def test_run_publish_failure_skips_db_update_and_continues_other_jobs(self):
        task = _make_task()
        job1 = _make_fleets_job(status=Job.RUNNING)
        job2 = _make_fleets_job(status=Job.RUNNING)

        with (
            patch(f"{_MOD}.settings") as mock_settings,
            patch(f"{_MOD}.Job") as mock_job_cls,
            patch.object(task, "update_job_status", return_value=True) as mock_update_status,
        ):
            mock_settings.LIMITS_MAX_FLEETS = 10
            mock_job_cls.objects.filter.return_value = [job1, job2]
            mock_job_cls.RUNNING_STATUSES = Job.RUNNING_STATUSES

            # Simulate update_job_status raising for job1 (publish failure) but succeeding for job2
            def fake_update(job):
                if job is job1:
                    raise Exception("broker down")
                return True

            mock_update_status.side_effect = fake_update

            task.run()

        # job1 raised — skipped; job2 processed normally
        mock_update_status.assert_any_call(job1)
        mock_update_status.assert_any_call(job2)
        assert mock_update_status.call_count == 2

    def test_update_job_status_skips_emit_for_pending_to_running_transition(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.PENDING)

        mock_runner = MagicMock()
        mock_runner.status.return_value = Job.RUNNING

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch.object(task, "to_running"),
            patch.object(task, "stop_job_if_timeout"),
        ):
            task.update_job_status(job)

        task.event_streams_client.emit_job_in_progress.assert_not_called()

    def test_to_running_emits_license_fee_after_job_started(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.PENDING)

        call_order = []
        task.event_streams_client.emit_job_started.side_effect = lambda j: call_order.append("started")
        task.event_streams_client.emit_license_fee.side_effect = lambda j: call_order.append("license")
        job.update_fields = MagicMock(side_effect=lambda f: call_order.append("db"))

        with patch(f"{_MOD}.JobEvent"):
            with patch(f"{_MOD}.django_timezone"):
                task.to_running(job)

        assert call_order == ["started", "license", "db"]
        task.event_streams_client.emit_license_fee.assert_called_once_with(job)


def test_filler_jobs_are_left_out_of_the_job_metrics():
    """A filler job neither counts as a terminal job nor contributes an execution duration."""
    task = _make_task()
    mock_job = MagicMock(spec=Job)
    mock_job.filler = True

    task._increment_terminal_counter(mock_job)
    task._record_execution_duration(mock_job)

    task.metrics.increment_jobs_terminal.assert_not_called()
    task.metrics.observe_job_execution_duration.assert_not_called()


def test_a_filler_job_that_ends_on_its_own_is_counted():
    """Reaching a terminal state here means the balancer did not ask for it.

    This is the counter that reveals a filler program which exits by itself, which
    the balancer would otherwise replace once a second forever.
    """
    task = _make_task()
    mock_job = MagicMock(spec=Job)
    mock_job.filler = True
    mock_job.status = Job.FAILED

    task._increment_terminal_counter(mock_job)

    task.metrics.increment_filler_jobs_ended.assert_called_once_with(Job.FAILED)
    task.metrics.increment_jobs_terminal.assert_not_called()


@pytest.mark.django_db
def test_an_inactive_project_does_not_fail_a_running_job():
    """A deactivated Code Engine project is a config problem, not a job that failed.

    Exercises the real FleetsRunner so the RunnerError comes from the inactive
    project rather than from a mock, which is how this reached production: the
    fleet keeps running in Code Engine while the row says FAILED.
    """
    project = TestUtils.get_or_create_ce_project(
        project_name="inactive-project",
        project_id="project-uuid",
        active=False,
        cos_bucket_user_data_name="bucket",
    )
    program = TestUtils.create_program("inactive-project-program", runner=Program.FLEETS, code_engine_project=project)
    job = Job.objects.create(
        program=program, author=program.author, runner=Program.FLEETS, status=Job.RUNNING, fleet_id="fleet-abc"
    )

    task = _make_task()
    task.update_job_status(job)

    job.refresh_from_db()
    assert job.status == Job.RUNNING
