"""Unit tests for ScheduleFleetsJobs."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from core.models import Config, Job
from core.services.runners import RunnerSubmitUncertainError, RunnerUnavailableError
from scheduler.tasks.schedule_fleets_jobs import ScheduleFleetsJobs

_MOD = "scheduler.tasks.schedule_fleets_jobs"


def _make_task():
    kill_signal = MagicMock()
    kill_signal.received = False
    return ScheduleFleetsJobs(kill_signal=kill_signal, metrics=MagicMock())


def test_fleets_execute_called_with_ctx():
    """submit is called with the job and the tracing context extracted from env_vars."""
    task = _make_task()

    mock_job = MagicMock()
    mock_job.fleet_id = "fleet-abc"
    mock_job.status = "PENDING"
    mock_job.gpu = False
    mock_job.env_vars = '{"traceparent": null}'
    mock_job.created = datetime(2026, 1, 1, tzinfo=timezone.utc)

    mock_ctx = MagicMock()

    with (
        patch(f"{_MOD}.get_jobs_to_schedule_fair_share", return_value=[mock_job]),
        patch.object(task.submitter, "submit", return_value=mock_job) as mock_execute,
        patch(f"{_MOD}.TraceContextTextMapPropagator") as mock_propagator,
    ):
        mock_propagator.return_value.extract.return_value = mock_ctx
        task._schedule_jobs_if_slots_available(max_slots_possible=5, number_of_slots_running=0)

    mock_execute.assert_called_once_with(mock_job, mock_ctx)


def test_add_queue_wait_time_metric_skips_filler_jobs():
    """Filler jobs skip the queue by design; the wait-time metric is only for real jobs."""
    task = _make_task()

    filler_job = MagicMock(spec=Job)
    filler_job.filler = True
    filler_job.created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    filler_job.gpu = False

    task.add_queue_wait_time_metric(filler_job)
    task.metrics.observe_queue_wait_time.assert_not_called()

    real_job = MagicMock(spec=Job)
    real_job.filler = False
    real_job.created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    real_job.gpu = False

    task.add_queue_wait_time_metric(real_job)
    task.metrics.observe_queue_wait_time.assert_called_once()


@pytest.mark.parametrize("error", [RunnerUnavailableError("Too Many Requests"), RunnerSubmitUncertainError("Timeout")])
def test_a_code_engine_failure_ends_the_tick(error):
    task = _make_task()
    jobs = [MagicMock(env_vars="{}"), MagicMock(env_vars="{}")]

    with (
        patch(f"{_MOD}.get_jobs_to_schedule_fair_share", return_value=jobs),
        patch.object(task.submitter, "submit", side_effect=error) as mock_execute,
    ):
        task._schedule_jobs_if_slots_available(max_slots_possible=5, number_of_slots_running=0)

    mock_execute.assert_called_once()


@pytest.mark.django_db
def test_run_skips_the_tick_while_code_engine_is_paused():
    Config.add_defaults()
    task = _make_task()

    task.submitter = MagicMock(paused=True)

    with patch(f"{_MOD}.get_jobs_to_schedule_fair_share") as mock_fair_share:
        task.run()

    mock_fair_share.assert_not_called()
