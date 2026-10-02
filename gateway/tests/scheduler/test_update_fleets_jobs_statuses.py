"""Unit tests for UpdateFleetsJobsStatuses."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from core.model_managers.job_events import JobEventContext, JobEventOrigin
from django.contrib.auth.models import User

from core.models import ComputeProfile, Job, JobEvent, Program
from core.services.job_transitions import JobTransitionService
from core.domain.exceptions.invalid_job_transition_exception import InvalidJobTransitionException
from core.services.runners import RunnerError
from scheduler.tasks.update_fleets_jobs_statuses import UpdateFleetsJobsStatuses, _STOPPING_DEADLINE_SECONDS
from tests.utils import TestUtils

_MOD = "scheduler.tasks.update_fleets_jobs_statuses"


def _make_transitions():
    """A JobTransitionService mock whose transitions write the job the way the real ones do; what they
    also owe (outbox, Kafka) is tested in tests/core/services/test_job_transitions.py."""
    transitions = MagicMock()

    def _pending_to_running(job, *, origin, context, job_fields=None):  # pylint: disable=unused-argument
        job.update_fields({"status": Job.RUNNING, **(job_fields or {})})

    def _to_terminal(job, status, *, origin, context, job_fields=None):  # pylint: disable=unused-argument
        job.update_fields({"status": status, **(job_fields or {})})

    def _to_stopping(job, *, origin, context):  # pylint: disable=unused-argument
        job.update_fields({"status": Job.STOPPING})

    transitions.pending_to_running = MagicMock(side_effect=_pending_to_running)
    transitions.to_terminal = MagicMock(side_effect=_to_terminal)
    transitions.to_stopping = MagicMock(side_effect=_to_stopping)
    return transitions


def _make_task():
    kill_signal = MagicMock()
    kill_signal.received = False
    task = UpdateFleetsJobsStatuses.__new__(UpdateFleetsJobsStatuses)
    task.kill_signal = kill_signal
    task.metrics = MagicMock()
    task.transitions = _make_transitions()
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
    job.compute_profile = "16x128"
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

        mock_running.assert_called_once_with(job)

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


class TestToRunning:
    """Tests for to_running()."""

    def test_job_transitions_from_pending_to_running(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.PENDING)

        task.to_running(job)

        assert job.status == Job.RUNNING
        task.transitions.pending_to_running.assert_called_once_with(
            job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS
        )
        task.transitions.running_to_running.assert_not_called()

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

        task.to_running(job)  # must not raise

        task.transitions.running_to_running.assert_not_called()

    def test_already_running_job_emits_in_progress_instead_of_transitioning(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        task.to_running(job)

        task.transitions.running_to_running.assert_called_once_with(job)
        task.transitions.pending_to_running.assert_not_called()


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
            patch(f"{_MOD}.get_runner", return_value=MagicMock()),
        ):
            mock_settings.PROGRAM_TIMEOUT = 1
            mock_event.objects.filter.return_value.order_by.return_value.first.return_value = past_event
            task.stop_job_if_timeout(job)

        # The cancel was accepted, so the poller confirms it from the task store on a later cycle.
        assert job.status == Job.STOPPING

    def test_cancels_the_fleet_before_marking_stopped(self):
        """The timeout must not just write STOPPED, it must cancel the Code Engine job too."""
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        past_event = MagicMock()
        past_event.created = datetime.now(timezone.utc) - timedelta(hours=100)
        mock_runner = MagicMock()

        with (
            patch(f"{_MOD}.settings") as mock_settings,
            patch(f"{_MOD}.JobEvent") as mock_event,
            patch(f"{_MOD}.get_runner", return_value=mock_runner) as mock_get_runner,
        ):
            mock_settings.PROGRAM_TIMEOUT = 1
            mock_event.objects.filter.return_value.order_by.return_value.first.return_value = past_event
            task.stop_job_if_timeout(job)

        mock_get_runner.assert_called_once_with(job)
        mock_runner.stop.assert_called_once_with()
        assert job.status == Job.STOPPING

    def test_leaves_the_job_alone_when_the_fleet_cannot_be_cancelled(self):
        """Behaviour change: the timeout used to write STOPPED regardless. A terminal status would
        report the job as finished while its fleet still holds the node, so it retries instead."""
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)

        past_event = MagicMock()
        past_event.created = datetime.now(timezone.utc) - timedelta(hours=100)
        mock_runner = MagicMock()
        mock_runner.stop.side_effect = RunnerError("Code Engine project 'p' is not active")

        with (
            patch(f"{_MOD}.settings") as mock_settings,
            patch(f"{_MOD}.JobEvent") as mock_event,
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
        ):
            mock_settings.PROGRAM_TIMEOUT = 1
            mock_event.objects.filter.return_value.order_by.return_value.first.return_value = past_event
            task.stop_job_if_timeout(job)

        assert job.status == Job.RUNNING
        task.transitions.to_terminal.assert_not_called()
        task.transitions.to_stopping.assert_not_called()

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

    def test_filler_job_never_stopped_regardless_of_age(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.RUNNING)
        job.filler = True

        past_event = MagicMock()
        past_event.created = datetime.now(timezone.utc) - timedelta(hours=1000)

        with (
            patch(f"{_MOD}.settings") as mock_settings,
            patch(f"{_MOD}.JobEvent") as mock_event,
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


@pytest.mark.django_db
def test_to_terminal_writes_the_job_through_the_real_service():
    """Nothing is mocked between the task and the database: the status, the wiped fields and the JobEvent land."""
    author = User.objects.create_user(username="update-fleets-real-service")
    job = Job.objects.create(
        author=author, runner=Program.FLEETS, status=Job.RUNNING, sub_status=Job.MAPPING, env_vars='{"k": "v"}'
    )
    task = _make_task()
    task.transitions = JobTransitionService(sender=MagicMock())

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
    task.transitions = JobTransitionService(sender=sender)
    mock_runner = MagicMock()
    mock_runner.status.return_value = Job.RUNNING

    with (
        patch(f"{_MOD}.get_runner", return_value=mock_runner),
        patch.object(task, "stop_job_if_timeout") as mock_timeout,
    ):
        task.update_job_status(job)

    sender.send.assert_called_once()
    mock_timeout.assert_called_once_with(job)


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


def _recent_stopping_event():
    event = MagicMock()
    event.created = datetime.now(timezone.utc)
    return event


def _old_stopping_event():
    event = MagicMock()
    event.created = datetime.now(timezone.utc) - timedelta(seconds=_STOPPING_DEADLINE_SECONDS + 60)
    return event


class TestDriveStopping:
    """A STOPPING job is driven to STOPPED by the scheduler, never by the stop request."""

    @pytest.mark.parametrize("task_state", [Job.STOPPED, Job.SUCCEEDED, Job.FAILED])
    def test_any_terminal_task_state_confirms_the_stop(self, task_state):
        """A task that finished before the cancel landed is still the stop the user asked for."""
        task = _make_task()
        job = _make_fleets_job(status=Job.STOPPING)
        runner = MagicMock()
        runner.status.return_value = task_state

        with patch(f"{_MOD}.get_runner", return_value=runner):
            changed = task.update_job_status(job)

        assert changed is True
        assert job.status == Job.STOPPED
        runner.stop.assert_not_called()

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

    def test_a_task_store_error_still_runs_the_deadline(self):
        """status() raises for a deleted program or an inactive project; the row must still leave STOPPING."""
        task = _make_task()
        job = _make_fleets_job(status=Job.STOPPING)
        runner = MagicMock()
        runner.status.side_effect = RunnerError("Code Engine project 'p' is not active")

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

    def test_a_filler_stopped_on_request_is_not_counted_as_ended_by_itself(self):
        task = _make_task()
        job = _make_fleets_job(status=Job.STOPPING)
        job.filler = True
        runner = MagicMock()
        runner.status.return_value = Job.STOPPED

        with patch(f"{_MOD}.get_runner", return_value=runner):
            task.update_job_status(job)

        assert job.status == Job.STOPPED
        task.metrics.increment_filler_jobs_ended.assert_not_called()


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

    def test_a_recent_stop_is_left_alone(self):
        author = User.objects.create_user(username="deadline-author-2")
        job = self._job(author)
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

        assert changed is False
        assert job.status == Job.STOPPING


class TestDriveStoppingFailurePaths:
    """What happens when Code Engine or its credentials are the problem."""

    def test_an_unusable_cos_credential_still_reaches_the_deadline(self):
        """status() re-raises ValueError for a renamed or emptied CE HMAC secret."""
        task = _make_task()
        job = _make_fleets_job(status=Job.STOPPING)
        runner = MagicMock()
        runner.status.side_effect = ValueError("CE secret 'cos-hmac-credential' not found in project 'p'")

        with (
            patch(f"{_MOD}.get_runner", return_value=runner),
            patch(f"{_MOD}.JobEvent") as mock_event,
        ):
            mock_event.objects.filter.return_value.order_by.return_value.first.return_value = _old_stopping_event()
            changed = task.update_job_status(job)

        assert changed is True
        assert job.status == Job.STOPPED
