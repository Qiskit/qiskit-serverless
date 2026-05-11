"""Unit tests for ScheduleQueuedJobs."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from scheduler.tasks.schedule_queued_jobs import ScheduleQueuedJobs

_MOD = "scheduler.tasks.schedule_queued_jobs"


def _make_task():
    kill_signal = MagicMock()
    kill_signal.received = False
    return ScheduleQueuedJobs(kill_signal=kill_signal, metrics=MagicMock())


def test_job_saved_with_update_fields_no_logs():
    """Job is saved with explicit update_fields"""
    task = _make_task()

    mock_job = MagicMock()
    mock_job.ray_job_id = "ray-abc"
    mock_job.fleet_id = "fleet-xyz"
    mock_job.status = "PENDING"
    mock_job.compute_resource = None
    mock_job.env_vars = '{"traceparent": null}'
    mock_job.created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    mock_job.gpu = False

    with (
        patch(f"{_MOD}.get_jobs_to_schedule_fair_share", return_value=[mock_job]),
        patch(f"{_MOD}.execute_job", return_value=mock_job),
        patch(f"{_MOD}.JobEvent"),
        patch(f"{_MOD}.TraceContextTextMapPropagator"),
        patch(f"{_MOD}.trace"),
    ):
        task._schedule_jobs_if_slots_available(  # pylint: disable=protected-access
            max_slots_possible=5, number_of_slots_running=0, gpu_job=False
        )

    mock_job.save.assert_called_once_with(update_fields=["status", "ray_job_id", "compute_resource", "fleet_id"])
