"""Unit tests for ScheduleFleetsJobs."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from scheduler.tasks.schedule_fleets_jobs import ScheduleFleetsJobs

_MOD = "scheduler.tasks.schedule_fleets_jobs"


def _make_task():
    kill_signal = MagicMock()
    kill_signal.received = False
    return ScheduleFleetsJobs(kill_signal=kill_signal, metrics=MagicMock())


def test_fleets_job_saved_with_update_fields():
    """Fleets job is saved with update_fields=["status", "fleet_id"] — no full save."""
    task = _make_task()

    mock_job = MagicMock()
    mock_job.fleet_id = "fleet-abc"
    mock_job.status = "PENDING"
    mock_job.gpu = False
    mock_job.env_vars = '{"traceparent": null}'
    mock_job.created = datetime(2026, 1, 1, tzinfo=timezone.utc)

    with (
        patch(f"{_MOD}.get_jobs_to_schedule_fair_share", return_value=[mock_job]),
        patch(f"{_MOD}.execute_job", return_value=mock_job),
        patch(f"{_MOD}.JobEvent"),
        patch(f"{_MOD}.TraceContextTextMapPropagator"),
        patch(f"{_MOD}.trace"),
    ):
        task._schedule_jobs_if_slots_available(max_slots_possible=5, number_of_slots_running=0)

    mock_job.save.assert_called_once_with(update_fields=["status", "fleet_id"])


def test_fleets_no_retry_on_save():
    """Fleets task never calls refresh_from_db — no retry loop."""
    task = _make_task()

    mock_job = MagicMock()
    mock_job.fleet_id = "fleet-xyz"
    mock_job.status = "PENDING"
    mock_job.gpu = False
    mock_job.env_vars = '{"traceparent": null}'
    mock_job.created = datetime(2026, 1, 1, tzinfo=timezone.utc)

    with (
        patch(f"{_MOD}.get_jobs_to_schedule_fair_share", return_value=[mock_job]),
        patch(f"{_MOD}.execute_job", return_value=mock_job),
        patch(f"{_MOD}.JobEvent"),
        patch(f"{_MOD}.TraceContextTextMapPropagator"),
        patch(f"{_MOD}.trace"),
    ):
        task._schedule_jobs_if_slots_available(max_slots_possible=5, number_of_slots_running=0)

    mock_job.refresh_from_db.assert_not_called()
