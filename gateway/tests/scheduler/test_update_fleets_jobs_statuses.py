"""Unit tests for UpdateFleetsJobsStatuses."""

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import ANY, MagicMock, patch

import pytest

from core.model_managers.job_events import JobEventContext, JobEventOrigin
from django.contrib.auth.models import User
from django.db.utils import OperationalError

from core.models import ComputeProfile, Job, JobEvent, Program
from core.services.job_transitions import JobTransitionService
from core.ibm_cloud.code_engine.fleets.cos import TaskTimes
from core.domain.exceptions.invalid_job_transition_exception import InvalidJobTransitionException
from core.services.runners import RunnerError, RunnerRetryableError
from scheduler.tasks.update_fleets_jobs_statuses import UpdateFleetsJobsStatuses, _STOPPING_DEADLINE_SECONDS
from tests.utils import TestUtils

_MOD = "scheduler.tasks.update_fleets_jobs_statuses"
_SCHEDULE = "scheduler.schedule"


def _make_transitions():
    """A JobTransitionService mock whose transitions write the job the way the real ones do; what they
    also owe (outbox, Kafka) is tested in tests/core/services/test_job_transitions.py."""
    transitions = MagicMock()

    def _pending_to_running(job, *, origin, context, job_fields=None):  # pylint: disable=unused-argument
        job.update_fields({"status": Job.RUNNING, **(job_fields or {})})

    def _to_terminal(job, status, *, origin, context, job_fields=None):  # pylint: disable=unused-argument
        job.update_fields({"status": status, **(job_fields or {})})

    def _try_stop(job, *, origin, context):  # pylint: disable=unused-argument
        job.update_fields({"status": Job.STOPPING})
        return True

    transitions.try_stop = MagicMock(side_effect=_try_stop)
    transitions.pending_to_running = MagicMock(side_effect=_pending_to_running)
    transitions.to_terminal = MagicMock(side_effect=_to_terminal)
    return transitions


def _make_canceller(transitions):
    """A canceller with a closed breaker that calls straight through to try_stop."""
    canceller = MagicMock()
    canceller.paused.return_value = False
    canceller.cancel.side_effect = lambda job, *, context: transitions.try_stop(
        job, origin=JobEventOrigin.SCHEDULER, context=context
    )
    return canceller


def _make_task():
    kill_signal = MagicMock()
    kill_signal.received = False
    task = UpdateFleetsJobsStatuses.__new__(UpdateFleetsJobsStatuses)
    task.kill_signal = kill_signal
    task.metrics = MagicMock()
    task.transitions = _make_transitions()
    task.canceller = _make_canceller(task.transitions)
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
    job.instance_crn = "crn:v1:bluemix:public:quantum-computing:us-east:a/abc:def::"
    job.ce_region = "us-east"
    job.filler = False
    job.in_terminal_state.return_value = status in Job.TERMINAL_STATUSES
    # what JobQuerySet.with_event_times() loads with each job
    job.created = datetime.now(timezone.utc)
    job.running_started_at = None
    job.running_ended_at = None
    job.first_running_at = None
    job.last_event_at = None

    def _apply_update_fields(fields_map):
        for field, value in fields_map.items():
            setattr(job, field, value)

    job.update_fields = MagicMock(side_effect=_apply_update_fields)
    job.started_at.return_value = datetime.now(timezone.utc) - timedelta(seconds=60)
    job.ended_at.return_value = datetime.now(timezone.utc)
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

    @pytest.mark.parametrize(
        "error", [RunnerError("Code Engine project 'p' is not active"), ValueError("CE secret not found")]
    )
    def test_status_error_leaves_the_status_alone_and_checks_the_timeout(self, error):
        """A ValueError from the COS client reaches the timeout too, instead of unwinding to run()."""
        task = _make_task()
        job = _make_fleets_job()

        mock_runner = MagicMock()
        mock_runner.status.side_effect = error

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch.object(task, "to_terminal") as mock_terminal,
            patch.object(task, "stop_job_if_timeout", return_value=False) as mock_timeout,
        ):
            result = task.update_job_status(job)

        mock_terminal.assert_not_called()
        mock_timeout.assert_called_once_with(job)
        assert result is False

    def test_succeeded_calls_to_terminal(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        mock_runner = MagicMock()
        mock_runner.status.return_value = Job.SUCCEEDED

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch.object(task, "to_terminal") as mock_terminal,
        ):
            task.update_job_status(job)

        mock_terminal.assert_called_once_with(job, Job.SUCCEEDED, mock_runner)

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

        mock_running.assert_called_once_with(job, mock_runner)

    def test_running_to_running_calls_to_running(self):
        """to_running is called unconditionally for a RUNNING poll result; it is the one
        that decides internally whether this is a PENDING->RUNNING transition or an
        already-RUNNING job that just needs an in-progress emit."""
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

        mock_running.assert_called_once_with(job, mock_runner)

    def test_none_status_skips_update_and_returns_false(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        mock_runner = MagicMock()
        mock_runner.status.return_value = None

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch.object(task, "stop_job_if_timeout", return_value=False),
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
            patch.object(task, "stop_job_if_timeout", return_value=False),
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
            patch.object(task, "stop_job_if_timeout", return_value=False) as mock_timeout,
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

        # the scheduler decides this one, there is no key in the task store to read the time from
        mock_terminal.assert_called_once_with(job, Job.FAILED)


class TestToTerminal:
    """Tests for to_terminal()."""

    def test_job_reaches_succeeded_state(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)
        job.sub_status = "pending"
        job.env_vars = '{"key": "value"}'

        with patch(f"{_MOD}.JobEvent"):
            task.to_terminal(job, Job.SUCCEEDED)

        assert job.status == Job.SUCCEEDED
        assert job.sub_status is None
        assert job.env_vars == "{}"
        task.transitions.to_terminal.assert_called_once_with(
            job,
            Job.SUCCEEDED,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.UPDATE_JOB_STATUS,
            job_fields={"sub_status": None, "env_vars": "{}"},
        )

    def test_a_succeeded_job_records_the_duration_billing_reads(self):
        """to_terminal owns this, so every route to SUCCEEDED gets it. The duration is from the job's own start and
        end, the ones billing reads, and not from the events."""
        task = _make_task()
        job = _make_fleets_job()
        started = datetime.now(timezone.utc) - timedelta(seconds=90)
        job.started_at.return_value = started
        job.ended_at.return_value = started + timedelta(seconds=30)
        job.program_id = None

        task.to_terminal(job, Job.SUCCEEDED)

        task.metrics.observe_job_execution_duration.assert_called_once_with(30.0, "custom")

    @pytest.mark.parametrize("missing", ["started_at", "ended_at"])
    def test_no_duration_is_recorded_without_both_ends(self, missing):
        task = _make_task()
        job = _make_fleets_job()
        job.started_at.return_value = datetime.now(timezone.utc) - timedelta(seconds=90)
        job.ended_at.return_value = datetime.now(timezone.utc)
        getattr(job, missing).return_value = None

        task.to_terminal(job, Job.SUCCEEDED)

        task.metrics.observe_job_execution_duration.assert_not_called()

    def test_a_duration_is_never_negative(self):
        """Two clocks: an end read from the task store can precede a start read from the events."""
        task = _make_task()
        job = _make_fleets_job()
        ended = datetime.now(timezone.utc)
        job.started_at.return_value = ended + timedelta(seconds=5)
        job.ended_at.return_value = ended

        task.to_terminal(job, Job.SUCCEEDED)

        assert task.metrics.observe_job_execution_duration.call_args.args[0] == 0

    def test_a_missing_end_time_from_the_task_store_is_logged(self, caplog):
        """The task store has just reported the state, so no time for it is Code Engine or COS failing."""
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)
        job.running_started_at = datetime.now(timezone.utc) - timedelta(seconds=30)
        runner = MagicMock()
        runner.get_task_times.return_value = TaskTimes(started_at=job.running_started_at)

        with caplog.at_level(logging.WARNING):
            task.to_terminal(job, Job.FAILED, runner)

        assert "no Code Engine end time for FAILED" in caplog.text
        assert "fleet_id=fleet-123" in caplog.text
        assert job.running_ended_at is None

    def test_an_end_time_from_the_task_store_is_stored_in_the_job_and_not_logged(self, caplog):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)
        job.running_started_at = datetime.now(timezone.utc) - timedelta(seconds=30)
        ended = datetime.now(timezone.utc) - timedelta(seconds=4)
        runner = MagicMock()
        runner.get_task_times.return_value = TaskTimes(finished_at=ended)

        with caplog.at_level(logging.WARNING):
            task.to_terminal(job, Job.FAILED, runner)

        assert job.running_ended_at == ended
        assert "no Code Engine" not in caplog.text

    def test_a_job_never_seen_running_gets_the_start_of_the_task_file(self):
        """It went from PENDING to its end between two scans, so the task file is the only place with its start."""
        task = _make_task()
        job = _make_fleets_job(status=Job.PENDING)
        started = datetime.now(timezone.utc) - timedelta(seconds=40)
        ended = datetime.now(timezone.utc) - timedelta(seconds=4)
        runner = MagicMock()
        runner.get_task_times.return_value = TaskTimes(started_at=started, finished_at=ended)

        task.to_terminal(job, Job.SUCCEEDED, runner)

        assert (job.running_started_at, job.running_ended_at) == (started, ended)

    def test_a_job_that_has_a_start_keeps_it(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)
        job.running_started_at = datetime.now(timezone.utc) - timedelta(seconds=60)
        kept = job.running_started_at
        runner = MagicMock()
        runner.get_task_times.return_value = TaskTimes(
            started_at=datetime.now(timezone.utc) - timedelta(seconds=50), finished_at=datetime.now(timezone.utc)
        )

        task.to_terminal(job, Job.SUCCEEDED, runner)

        assert job.running_started_at == kept

    def test_a_missing_start_for_a_job_never_seen_running_is_logged(self, caplog):
        task = _make_task()
        job = _make_fleets_job(status=Job.PENDING)
        runner = MagicMock()
        runner.get_task_times.return_value = TaskTimes(finished_at=datetime.now(timezone.utc))

        with caplog.at_level(logging.WARNING):
            task.to_terminal(job, Job.FAILED, runner)

        assert "no Code Engine start time" in caplog.text

    def test_a_missing_start_for_a_job_that_has_one_is_not_logged(self, caplog):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)
        job.running_started_at = datetime.now(timezone.utc) - timedelta(seconds=60)
        runner = MagicMock()
        runner.get_task_times.return_value = TaskTimes(finished_at=datetime.now(timezone.utc))

        with caplog.at_level(logging.WARNING):
            task.to_terminal(job, Job.FAILED, runner)

        assert "no Code Engine start time" not in caplog.text

    def test_a_status_the_scheduler_decided_reads_no_time_and_logs_nothing(self, caplog):
        """A timeout or an unconfirmed stop has no task in the task store: no time is the normal case."""
        task = _make_task()
        job = _make_fleets_job(status=Job.PENDING)

        with caplog.at_level(logging.WARNING):
            task.to_terminal(job, Job.STOPPED)

        assert "no Code Engine" not in caplog.text
        assert job.running_started_at is None
        assert job.running_ended_at is None

    def test_the_end_time_is_read_before_the_transition(self):
        """The transition holds a transaction and a lock on the job: the COS call must not be inside it."""
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)
        calls = []
        runner = MagicMock()
        runner.get_task_times.side_effect = lambda: calls.append("get_task_times") or TaskTimes()
        task.transitions.to_terminal.side_effect = lambda *a, **k: calls.append("to_terminal")

        task.to_terminal(job, Job.FAILED, runner)

        assert calls == ["get_task_times", "to_terminal"]

    def test_job_reaches_failed_state(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)
        job.sub_status = "pending"
        job.env_vars = '{"key": "value"}'

        task.to_terminal(job, Job.FAILED)

        assert job.status == Job.FAILED
        assert job.sub_status is None
        assert job.env_vars == "{}"
        task.transitions.to_terminal.assert_called_once_with(
            job,
            Job.FAILED,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.UPDATE_JOB_STATUS,
            job_fields={"sub_status": None, "env_vars": "{}"},
        )

    def test_to_terminal_never_sends_an_in_progress_event(self):
        """Kafka publishing for a terminal job happens only via the outbox task."""
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        with patch(f"{_MOD}.JobEvent"):
            task.to_terminal(job, Job.SUCCEEDED)

        task.transitions.running_to_running.assert_not_called()

    def test_does_not_raise_when_the_job_already_turned_terminal(self):
        """A user-initiated stop can race this poll and win it first: the transition then
        raises InvalidJobTransitionException, which must not crash the tick or count the
        terminal metric for a transition that never happened."""
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)
        task.transitions.to_terminal.side_effect = InvalidJobTransitionException(
            "Job x: invalid transition STOPPED -> SUCCEEDED"
        )

        task.to_terminal(job, Job.SUCCEEDED)  # must not raise

        task.metrics.increment_jobs_terminal.assert_not_called()
        task.metrics.observe_job_execution_duration.assert_not_called()


class TestToRunning:
    """Tests for to_running()."""

    def test_job_transitions_from_pending_to_running(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.PENDING)
        runner = MagicMock()
        runner.get_task_times.return_value = TaskTimes()

        task.to_running(job, runner)

        assert job.status == Job.RUNNING
        task.transitions.pending_to_running.assert_called_once_with(
            job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS
        )
        assert job.running_started_at is None
        task.transitions.running_to_running.assert_not_called()

    def test_the_transition_gets_the_time_code_engine_started_the_job(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.PENDING)
        started = datetime.now(timezone.utc) - timedelta(seconds=4)
        runner = MagicMock()
        runner.get_task_times.return_value = TaskTimes(started_at=started)

        task.to_running(job, runner)

        task.transitions.pending_to_running.assert_called_once_with(
            job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS
        )
        assert job.running_started_at == started

    def test_a_missing_start_time_from_the_task_store_is_logged(self, caplog):
        task = _make_task()
        job = _make_fleets_job(status=Job.PENDING)
        runner = MagicMock()
        runner.get_task_times.return_value = TaskTimes()

        with caplog.at_level(logging.WARNING):
            task.to_running(job, runner)

        assert "no Code Engine start time" in caplog.text
        assert "fleet_id=fleet-123" in caplog.text

    def test_a_start_time_from_the_task_store_is_not_logged(self, caplog):
        task = _make_task()
        job = _make_fleets_job(status=Job.PENDING)
        runner = MagicMock()
        runner.get_task_times.return_value = TaskTimes(started_at=datetime.now(timezone.utc))

        with caplog.at_level(logging.WARNING):
            task.to_running(job, runner)

        assert "no Code Engine time" not in caplog.text

    def test_the_start_time_is_read_before_the_transition(self):
        """The transition holds a transaction and a lock on the job: the COS call must not be inside it."""
        task = _make_task()
        job = _make_fleets_job(status=Job.PENDING)
        calls = []
        runner = MagicMock()
        runner.get_task_times.side_effect = lambda: calls.append("get_task_times") or TaskTimes()
        task.transitions.pending_to_running.side_effect = lambda *a, **k: calls.append("pending_to_running")

        task.to_running(job, runner)

        assert calls == ["get_task_times", "pending_to_running"]

    def test_does_not_send_in_progress_when_the_job_already_turned_terminal(self):
        """A user-initiated stop can race this poll and win it first: the transition then
        raises InvalidJobTransitionException. Sending an in-progress event for an
        already-terminal job would be wrong, so this must skip it entirely, not just the
        transition."""
        task = _make_task()
        job = _make_fleets_job(status=Job.PENDING)
        task.transitions.pending_to_running.side_effect = InvalidJobTransitionException(
            "Job x: invalid transition STOPPED -> RUNNING"
        )

        task.to_running(job, MagicMock())  # must not raise

        task.transitions.running_to_running.assert_not_called()

    def test_already_running_job_emits_in_progress_instead_of_transitioning(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)
        runner = MagicMock()

        task.to_running(job, runner)

        task.transitions.running_to_running.assert_called_once_with(job)
        task.transitions.pending_to_running.assert_not_called()
        runner.get_task_times.assert_not_called()

    def test_an_already_running_job_does_not_read_the_start_time_again(self):
        """The start time is read once per job, in the transition, not on every tick."""
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)
        runner = MagicMock()

        task.to_running(job, runner)

        runner.get_task_times.assert_not_called()


class TestStopJobIfTimeout:
    """Tests for stop_job_if_timeout()."""

    def test_a_timed_out_job_goes_to_stopping(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        past_event = MagicMock()
        past_event.created = datetime.now(timezone.utc) - timedelta(hours=100)
        job.last_event_at = past_event.created

        with (
            patch(f"{_SCHEDULE}.settings") as mock_settings,
            patch(f"{_SCHEDULE}.JobEvent") as mock_event,
        ):
            mock_settings.PROGRAM_TIMEOUT = 1
            mock_event.objects.filter.return_value.order_by.return_value.first.return_value = past_event
            task.stop_job_if_timeout(job)

        # The cancel was accepted, so the poller confirms it from the task store on a later cycle.
        assert job.status == Job.STOPPING

    def test_the_timeout_cancels_the_fleet_and_records_stopping(self):
        """The timeout must cancel the Code Engine job, not just write a status."""
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        past_event = MagicMock()
        past_event.created = datetime.now(timezone.utc) - timedelta(hours=100)
        job.last_event_at = past_event.created

        with (
            patch(f"{_SCHEDULE}.settings") as mock_settings,
            patch(f"{_SCHEDULE}.JobEvent") as mock_event,
        ):
            mock_settings.PROGRAM_TIMEOUT = 1
            mock_event.objects.filter.return_value.order_by.return_value.first.return_value = past_event
            task.stop_job_if_timeout(job)

        task.transitions.try_stop.assert_called_once()
        assert job.status == Job.STOPPING

    def test_a_fleet_already_gone_is_still_counted(self):
        """stop() writes STOPPED itself when Code Engine has no fleet left, so to_terminal here would
        be STOPPED to STOPPED, which is rejected and counts nothing."""
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        def _wrote_stopped(job, **kwargs):  # pylint: disable=unused-argument
            job.update_fields({"status": Job.STOPPED})
            return False

        past_event = MagicMock()
        past_event.created = datetime.now(timezone.utc) - timedelta(hours=100)
        job.last_event_at = past_event.created
        task.transitions.try_stop.side_effect = _wrote_stopped
        # what the real service answers for STOPPED -> STOPPED
        task.transitions.to_terminal.side_effect = InvalidJobTransitionException("STOPPED -> STOPPED")

        with (
            patch(f"{_SCHEDULE}.settings") as mock_settings,
            patch(f"{_SCHEDULE}.JobEvent") as mock_event,
        ):
            mock_settings.PROGRAM_TIMEOUT = 1
            mock_event.objects.filter.return_value.order_by.return_value.first.return_value = past_event
            task.stop_job_if_timeout(job)

        assert job.status == Job.STOPPED
        task.metrics.increment_jobs_terminal.assert_called_once_with(provider=ANY, final_status=Job.STOPPED)

    @pytest.mark.parametrize(
        "error",
        [
            RunnerRetryableError("Too Many Requests"),
            RunnerError("Forbidden"),
            InvalidJobTransitionException("invalid transition STOPPED -> STOPPING"),
        ],
        ids=["undeliverable", "refused", "lost-the-race"],
    )
    def test_a_cancel_that_did_not_land_leaves_the_job_alone(self, error):
        """Writing STOPPED on a cancel that never landed would claim a stop that never happened and
        strand the fleet. The row keeps its status and a later tick asks again."""
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        past_event = MagicMock()
        past_event.created = datetime.now(timezone.utc) - timedelta(hours=100)
        job.last_event_at = past_event.created
        task.transitions.try_stop.side_effect = error

        with (
            patch(f"{_SCHEDULE}.settings") as mock_settings,
            patch(f"{_SCHEDULE}.JobEvent") as mock_event,
        ):
            mock_settings.PROGRAM_TIMEOUT = 1
            mock_event.objects.filter.return_value.order_by.return_value.first.return_value = past_event
            changed = task.stop_job_if_timeout(job)

        assert changed is False
        assert job.status == Job.RUNNING
        task.transitions.to_terminal.assert_not_called()

    def test_a_paused_region_sends_no_cancel(self):
        """One try per tick costs nothing while the region's breaker is open."""
        task = _make_task()
        task.canceller.paused.return_value = True
        job = _make_fleets_job(status=Job.RUNNING)

        past_event = MagicMock()
        past_event.created = datetime.now(timezone.utc) - timedelta(hours=100)
        job.last_event_at = past_event.created

        with (
            patch(f"{_SCHEDULE}.settings") as mock_settings,
            patch(f"{_SCHEDULE}.JobEvent") as mock_event,
        ):
            mock_settings.PROGRAM_TIMEOUT = 1
            mock_event.objects.filter.return_value.order_by.return_value.first.return_value = past_event
            changed = task.stop_job_if_timeout(job)

        assert changed is False
        assert job.status == Job.RUNNING
        task.canceller.cancel.assert_not_called()

    def test_job_unchanged_when_within_timeout(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        recent_event = MagicMock()
        recent_event.created = datetime.now(timezone.utc) - timedelta(minutes=5)
        job.last_event_at = recent_event.created

        with (
            patch(f"{_SCHEDULE}.settings") as mock_settings,
            patch(f"{_SCHEDULE}.JobEvent") as mock_event,
        ):
            mock_settings.PROGRAM_TIMEOUT = 24
            mock_event.objects.filter.return_value.order_by.return_value.first.return_value = recent_event
            task.stop_job_if_timeout(job)

        assert job.status == Job.RUNNING
        job.update_fields.assert_not_called()

    def test_a_recent_event_read_again_keeps_the_job_running(self):
        """The loaded time is from before the pass; an event written since then keeps the job."""
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)
        job.last_event_at = datetime.now(timezone.utc) - timedelta(hours=100)

        recent_event = MagicMock()
        recent_event.created = datetime.now(timezone.utc)

        with (
            patch(f"{_SCHEDULE}.settings") as mock_settings,
            patch(f"{_SCHEDULE}.JobEvent") as mock_event,
        ):
            mock_settings.PROGRAM_TIMEOUT = 1
            mock_event.objects.filter.return_value.order_by.return_value.first.return_value = recent_event
            changed = task.stop_job_if_timeout(job)

        assert changed is False
        task.canceller.cancel.assert_not_called()

    def test_a_recent_loaded_time_reads_no_events(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)
        job.last_event_at = datetime.now(timezone.utc)

        with patch(f"{_SCHEDULE}.JobEvent") as mock_event:
            task.stop_job_if_timeout(job)

        mock_event.objects.filter.assert_not_called()

    def test_filler_job_never_stopped_regardless_of_age(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)
        job.filler = True

        past_event = MagicMock()
        past_event.created = datetime.now(timezone.utc) - timedelta(hours=1000)

        with (
            patch(f"{_SCHEDULE}.settings") as mock_settings,
            patch(f"{_SCHEDULE}.JobEvent") as mock_event,
        ):
            mock_settings.PROGRAM_TIMEOUT = 1
            mock_event.objects.filter.return_value.order_by.return_value.first.return_value = past_event
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
            mock_job_cls.objects.filter.return_value.select_related.return_value.with_event_times.return_value = [
                job1,
                job2,
            ]
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
            mock_job_cls.objects.filter.return_value.select_related.return_value.with_event_times.return_value = [
                job1,
                job2,
            ]
            mock_job_cls.RUNNING_STATUSES = Job.RUNNING_STATUSES
            task.run()

        mock_logger.info.assert_called_with("Updated %s Fleets jobs.", 2)

    def test_counts_every_job_checked_and_not_only_the_ones_that_changed(self):
        task = _make_task()
        changed = _make_fleets_job()
        unreadable = _make_fleets_job()

        with (
            patch(f"{_MOD}.settings") as mock_settings,
            patch(f"{_MOD}.Job") as mock_job_cls,
            patch.object(task, "update_job_status", side_effect=[True, False]),
        ):
            mock_settings.LIMITS_MAX_FLEETS = 10
            mock_job_cls.objects.filter.return_value.select_related.return_value.with_event_times.return_value = [
                changed,
                unreadable,
            ]
            mock_job_cls.RUNNING_STATUSES = Job.RUNNING_STATUSES
            task.run()

        task.metrics.increment_task_items.assert_called_once_with(task.name, 2)


class TestEventStreamsIntegration:
    """Tests that emit methods are called at the right lifecycle points."""

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

        task.transitions.running_to_running.assert_called_once_with(job)

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
            mock_job_cls.objects.filter.return_value.select_related.return_value.with_event_times.return_value = [
                job1,
                job2,
            ]
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


@pytest.mark.django_db
def test_to_terminal_writes_the_job_through_the_real_service():
    """Nothing is mocked between the task and the database: the status, the wiped fields and the JobEvent land."""
    author = User.objects.create_user(username="update-fleets-real-service")
    job = Job.objects.create(
        author=author, runner=Program.FLEETS, status=Job.RUNNING, sub_status=Job.MAPPING, env_vars='{"k": "v"}'
    )
    task = _make_task()
    task.transitions = JobTransitionService(billing_sender=MagicMock())

    task.to_terminal(job, Job.FAILED)

    job.refresh_from_db()
    assert job.status == Job.FAILED
    assert job.sub_status is None
    assert job.env_vars == "{}"
    assert JobEvent.objects.filter(job=job, data__status=Job.FAILED).count() == 1
    task.metrics.increment_jobs_terminal.assert_called_once()


@pytest.mark.django_db
def test_a_running_job_checks_the_timeout_even_when_the_in_progress_send_fails():
    """A Kafka outage on the in-progress event must not skip the timeout check for that job: the real
    service swallows the failure, so nothing reaches the task."""
    author = User.objects.create_user(username="update-fleets-kafka-down")
    profile = ComputeProfile.objects.create(compute_profile_id="16x128", cpu="16", memory="128")
    job = Job.objects.create(
        author=author,
        runner=Program.FLEETS,
        fleet_id="fleet-123",
        instance_crn="crn:v1:bluemix:public:quantum-computing:us-east:a/acct:inst::",
        compute_profile_fk=profile,
        status=Job.RUNNING,
    )
    JobEvent.objects.add_status_event(
        job_id=job.id, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS, status=Job.RUNNING
    )
    sender = MagicMock()
    sender.send.side_effect = RuntimeError("kafka down")
    task = _make_task()
    task.transitions = JobTransitionService(billing_sender=sender)
    mock_runner = MagicMock()
    mock_runner.status.return_value = Job.RUNNING

    job = Job.objects.with_event_times().get(pk=job.pk)

    with (
        patch(f"{_MOD}.get_runner", return_value=mock_runner),
        patch.object(task, "stop_job_if_timeout") as mock_timeout,
    ):
        task.update_job_status(job)

    sender.send.assert_called_once()
    mock_timeout.assert_called_once_with(job)


@pytest.mark.django_db
def test_a_db_error_on_one_job_still_updates_the_others_and_reaches_the_scheduler():
    author = User.objects.create_user(username="update-fleets-db-down")
    for fleet_id in ("fleet-a", "fleet-b"):
        Job.objects.create(author=author, runner=Program.FLEETS, fleet_id=fleet_id, status=Job.RUNNING)
    task = _make_task()
    updated = []

    def deadlock_on_the_first_job(job):
        if not updated:
            updated.append(job.fleet_id)
            raise OperationalError("deadlock detected")
        updated.append(job.fleet_id)
        return True

    with (
        patch.object(task, "update_job_status", side_effect=deadlock_on_the_first_job),
        pytest.raises(OperationalError),
    ):
        task.run()

    assert sorted(updated) == ["fleet-a", "fleet-b"]
    task.metrics.increment_task_items.assert_called_once_with(task.name, 2)


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
    job = Job.objects.with_event_times().get(pk=job.pk)

    task = _make_task()
    task.update_job_status(job)

    job.refresh_from_db()
    assert job.status == Job.RUNNING


def _recent_stopping_event():
    event = MagicMock()
    event.created = datetime.now(timezone.utc)
    return event


def _old_stopping_event():
    event = MagicMock()
    event.created = datetime.now(timezone.utc) - timedelta(seconds=_STOPPING_DEADLINE_SECONDS + 60)
    return event


class TestStoppingJobs:
    """A STOPPING job is driven to a terminal status by the scheduler, never by the stop request."""

    @pytest.mark.parametrize("task_state", [Job.STOPPED, Job.SUCCEEDED, Job.FAILED])
    def test_the_task_stores_terminal_status_wins_over_the_stop(self, task_state):
        """A job that finished before its cancel landed really did finish. Writing STOPPED instead
        reports it as cancelled, which hides a failed job's error from the caller.

        The task store is COS, not the Code Engine API, so this read must never consult the breaker:
        gate it and a STOPPING row could never reach a terminal status during a Code Engine outage.
        """
        task = _make_task()
        job = _make_fleets_job(status=Job.STOPPING)
        runner = MagicMock()
        runner.status.return_value = task_state

        with (
            patch(f"{_MOD}.get_runner", return_value=runner),
            patch(f"{_MOD}.JobEvent") as mock_event,
        ):
            # no RUNNING event, so the duration is skipped: this test is about the status
            mock_event.objects.filter.return_value.order_by.return_value.first.return_value = None
            changed = task.update_job_status(job)

        assert changed is True
        assert job.status == task_state
        runner.stop.assert_not_called()
        task.canceller.paused.assert_not_called()

    def test_a_running_task_is_left_alone_and_no_cancel_is_sent(self):
        """Whoever asked for the stop already sent the cancel. The poller only observes."""
        task = _make_task()
        job = _make_fleets_job(status=Job.STOPPING)
        runner = MagicMock()
        runner.status.return_value = Job.RUNNING

        with (
            patch(f"{_MOD}.get_runner", return_value=runner),
            patch(f"{_MOD}.JobEvent") as mock_event,
        ):
            mock_event.objects.filter.return_value.order_by.return_value.first.return_value = _recent_stopping_event()
            changed = task.update_job_status(job)

        assert changed is False
        assert job.status == Job.STOPPING
        runner.stop.assert_not_called()
        task.transitions.running_to_running.assert_not_called()

    @pytest.mark.parametrize(
        "error", [RunnerError("project 'p' is not active"), ValueError("CE secret not found in project 'p'")]
    )
    def test_an_unreadable_task_store_still_runs_the_deadline(self, error):
        """status() raises RunnerError for an inactive project and ValueError for a bad COS secret."""
        task = _make_task()
        job = _make_fleets_job(status=Job.STOPPING)
        runner = MagicMock()
        runner.status.side_effect = error

        with (
            patch(f"{_MOD}.get_runner", return_value=runner),
            patch(f"{_MOD}.JobEvent") as mock_event,
        ):
            mock_event.objects.filter.return_value.order_by.return_value.first.return_value = _old_stopping_event()
            changed = task.update_job_status(job)

        assert changed is True
        assert job.status == Job.STOPPED

    def test_the_deadline_writes_stopped_without_confirmation(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.STOPPING)
        runner = MagicMock()
        runner.status.return_value = Job.RUNNING

        with (
            patch(f"{_MOD}.get_runner", return_value=runner),
            patch(f"{_MOD}.JobEvent") as mock_event,
        ):
            mock_event.objects.filter.return_value.order_by.return_value.first.return_value = _old_stopping_event()
            changed = task.update_job_status(job)

        assert changed is True
        assert job.status == Job.STOPPED

    def test_a_stopping_job_with_no_fleet_stops_at_once(self):
        """The branch sits before the fleet_id check, which would otherwise return and never look again."""
        task = _make_task()
        job = _make_fleets_job(status=Job.STOPPING, fleet_id=None)

        with patch(f"{_MOD}.get_runner") as mock_get_runner:
            changed = task.update_job_status(job)

        assert changed is True
        assert job.status == Job.STOPPED
        mock_get_runner.assert_not_called()

    def test_a_draining_filler_still_reaches_the_deadline(self):
        """A draining filler is not exempt from the stopping deadline, only from PROGRAM_TIMEOUT.
        Exempt it from both and it stays in STOPPING for ever: the balancer skips rows already
        STOPPING and nothing else ends a filler."""
        task = _make_task()
        job = _make_fleets_job(status=Job.STOPPING)
        job.filler = True
        runner = MagicMock()
        runner.status.return_value = Job.RUNNING

        with (
            patch(f"{_MOD}.get_runner", return_value=runner),
            patch(f"{_MOD}.JobEvent") as mock_event,
        ):
            mock_event.objects.filter.return_value.order_by.return_value.first.return_value = _old_stopping_event()
            changed = task.update_job_status(job)

        assert changed is True
        assert job.status == Job.STOPPED

    def test_a_filler_stopped_on_request_is_counted_as_stopped_not_as_ended(self):
        """STOPPING means something asked for the stop, so it is counted here and not by the balancer,
        which cannot know whether the cancel it sent ever landed."""
        task = _make_task()
        job = _make_fleets_job(status=Job.STOPPING)
        job.filler = True
        runner = MagicMock()
        runner.status.return_value = Job.STOPPED

        with patch(f"{_MOD}.get_runner", return_value=runner):
            task.update_job_status(job)

        assert job.status == Job.STOPPED
        task.metrics.increment_filler_jobs_stopped.assert_called_once()
        task.metrics.increment_filler_jobs_ended.assert_not_called()

    def test_a_filler_that_finished_before_its_cancel_landed_is_counted_as_ended(self):
        """The balancer asked, but the task finished first, so counting it as stopped would overstate
        what the balancer freed."""
        task = _make_task()
        job = _make_fleets_job(status=Job.STOPPING)
        job.filler = True
        runner = MagicMock()
        runner.status.return_value = Job.SUCCEEDED

        with patch(f"{_MOD}.get_runner", return_value=runner):
            task.update_job_status(job)

        assert job.status == Job.SUCCEEDED
        task.metrics.increment_filler_jobs_ended.assert_called_once_with(Job.SUCCEEDED)
        task.metrics.increment_filler_jobs_stopped.assert_not_called()


@pytest.mark.django_db
class TestStoppingDeadlineAgainstTheDatabase:
    """The deadline query runs for real here. Patched JobEvent mocks cannot catch a wrong filter."""

    def _job(self, author):
        return Job.objects.create(author=author, runner=Program.FLEETS, status=Job.STOPPING, fleet_id="fleet-abc")

    def test_a_chatty_sub_status_does_not_push_the_deadline_out(self):
        """The query must read the earliest STOPPING event, not the latest event of any kind."""
        author = User.objects.create_user(username="deadline-author")
        job = self._job(author)
        JobEvent.objects.add_status_event(
            job_id=job.id,
            origin=JobEventOrigin.API,
            context=JobEventContext.STOP_JOB,
            status=Job.STOPPING,
        )
        JobEvent.objects.add_sub_status_event(
            job_id=job.id,
            origin=JobEventOrigin.API,
            context=JobEventContext.UPDATE_JOB_STATUS,
            sub_status=Job.EXECUTING_QPU,
        )
        # The stop was asked for long ago; the sub_status report is from just now.
        JobEvent.objects.filter(job=job, data__status=Job.STOPPING).update(
            created=datetime.now(timezone.utc) - timedelta(seconds=_STOPPING_DEADLINE_SECONDS + 60)
        )

        task = _make_task()
        runner = MagicMock()
        runner.status.return_value = Job.RUNNING

        with patch(f"{_MOD}.get_runner", return_value=runner):
            changed = task.update_job_status(job)

        assert changed is True, "the deadline never fired, so the query read the wrong event"
        assert job.status == Job.STOPPED

    def test_an_older_event_of_another_kind_does_not_start_the_clock(self):
        """Pins the data__status filter. Without it the QUEUED creation event starts the clock, and
        every stopping job is forced to STOPPED on its first poll without ever being confirmed."""
        author = User.objects.create_user(username="deadline-author-3")
        job = self._job(author)
        JobEvent.objects.add_status_event(
            job_id=job.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.SCHEDULE_JOBS,
            status=Job.QUEUED,
        )
        JobEvent.objects.filter(job=job, data__status=Job.QUEUED).update(
            created=datetime.now(timezone.utc) - timedelta(seconds=_STOPPING_DEADLINE_SECONDS * 4)
        )
        # The cancel was accepted a moment ago, so the deadline must not have started yet.
        JobEvent.objects.add_status_event(
            job_id=job.id,
            origin=JobEventOrigin.API,
            context=JobEventContext.STOP_JOB,
            status=Job.STOPPING,
        )

        task = _make_task()
        runner = MagicMock()
        runner.status.return_value = Job.RUNNING

        with patch(f"{_MOD}.get_runner", return_value=runner):
            changed = task.update_job_status(job)

        assert changed is False, "an older event of another kind started the deadline"
        assert job.status == Job.STOPPING


def _real_fleets_job(username, status=Job.RUNNING, event_status=Job.RUNNING, event_age=timedelta(minutes=5)):
    """A Fleets job in the database with one status event written `event_age` ago."""
    job = Job.objects.create(
        author=User.objects.create_user(username=username),
        runner=Program.FLEETS,
        fleet_id=f"fleet-{username}",
        instance_crn="crn:v1:bluemix:public:quantum-computing:us-east:a/acct:inst::",
        status=status,
    )
    JobEvent.objects.add_status_event(
        job_id=job.id, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS, status=event_status
    )
    JobEvent.objects.filter(job=job).update(created=datetime.now(timezone.utc) - event_age)
    return job


def _run_real_pass(reported_status, on_status=None):
    """Run one pass with a fake runner and a fake canceller. Returns the sender."""
    sender = MagicMock()
    task = _make_task()
    task.transitions = JobTransitionService(billing_sender=sender)

    def status():
        if on_status:
            on_status()
        return reported_status

    runner = MagicMock()
    runner.status.side_effect = status
    runner.get_task_times.return_value = TaskTimes()  # no Code Engine time: the job's own clock is used
    with patch(f"{_MOD}.get_runner", return_value=runner):
        task.run()
    return sender


@pytest.mark.django_db
class TestEventTimesLoadedWithTheJobs:
    """run() loads the event times with the jobs. These check the results match the per-job queries."""

    def test_the_usage_start_time_is_the_first_running_event(self):
        job = _real_fleets_job("usage-start", event_age=timedelta(hours=2))
        JobEvent.objects.add_status_event(
            job_id=job.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.UPDATE_JOB_STATUS,
            status=Job.RUNNING,
        )

        sender = _run_real_pass(Job.RUNNING)

        payload = sender.send.call_args.args[0]
        assert JobEvent.objects.first_running_at(job.id).isoformat() in str(payload)

    def test_a_job_past_the_timeout_is_stopped(self):
        job = _real_fleets_job("timed-out", event_age=timedelta(hours=100))

        _run_real_pass(Job.RUNNING)

        job.refresh_from_db()
        assert job.status == Job.STOPPING

    def test_an_event_written_after_the_jobs_were_loaded_keeps_the_job_running(self):
        job = _real_fleets_job("fresh-event", event_age=timedelta(hours=100))

        def write_an_event():
            JobEvent.objects.add_status_event(
                job_id=job.id, origin=JobEventOrigin.API, context=JobEventContext.UPDATE_JOB_STATUS, status=Job.RUNNING
            )

        _run_real_pass(Job.RUNNING, on_status=write_an_event)

        job.refresh_from_db()
        assert job.status == Job.RUNNING

    def test_a_job_that_starts_after_a_long_wait_is_not_stopped(self):
        job = _real_fleets_job(
            "long-pending", status=Job.PENDING, event_status=Job.PENDING, event_age=timedelta(hours=100)
        )

        _run_real_pass(Job.RUNNING)

        job.refresh_from_db()
        assert job.status == Job.RUNNING

    def test_a_job_with_no_events_counts_from_its_creation(self):
        job = _real_fleets_job("no-events")
        JobEvent.objects.filter(job=job).delete()
        Job.objects.filter(pk=job.pk).update(created=datetime.now(timezone.utc) - timedelta(hours=100))

        _run_real_pass(None)

        job.refresh_from_db()
        assert job.status == Job.STOPPING
