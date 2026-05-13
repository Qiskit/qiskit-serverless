"""Unit tests for ScheduleFleetsJobs."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from scheduler.tasks.schedule_fleets_jobs import ScheduleFleetsJobs

_MOD = "scheduler.tasks.schedule_fleets_jobs"


def _make_task():
    kill_signal = MagicMock()
    kill_signal.received = False
    return ScheduleFleetsJobs(kill_signal=kill_signal, metrics=MagicMock())


def test_fleets_execute_called_with_ctx():
    """execute_fleets is called with the job and the tracing context extracted from env_vars."""
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
        patch(f"{_MOD}.execute_fleets", return_value=mock_job) as mock_execute,
        patch(f"{_MOD}.TraceContextTextMapPropagator") as mock_propagator,
    ):
        mock_propagator.return_value.extract.return_value = mock_ctx
        task._schedule_jobs_if_slots_available(max_slots_possible=5, number_of_slots_running=0)

    mock_execute.assert_called_once_with(mock_job, mock_ctx)
