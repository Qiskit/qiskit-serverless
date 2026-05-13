"""Unit tests for ScheduleRayJobs."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from scheduler.tasks.schedule_queued_jobs import ScheduleRayJobs

_MOD = "scheduler.tasks.schedule_queued_jobs"


def _make_task():
    kill_signal = MagicMock()
    kill_signal.received = False
    return ScheduleRayJobs(kill_signal=kill_signal, metrics=MagicMock())


def test_job_saved_with_save_direct():
    """Job is persisted via save_direct to bypass optimistic-locking validation."""
    task = _make_task()

    mock_job = MagicMock()
    mock_job.id = 42
    mock_job.ray_job_id = "ray-abc"
    mock_job.status = "PENDING"
    mock_job.compute_resource = None
    mock_job.env_vars = '{"traceparent": null}'
    mock_job.created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    mock_job.gpu = False

    with (
        patch(f"{_MOD}.get_jobs_to_schedule_fair_share", return_value=[mock_job]),
        patch(f"{_MOD}.execute_ray_job", return_value=mock_job),
        patch(f"{_MOD}.JobEvent"),
        patch(f"{_MOD}.TraceContextTextMapPropagator"),
        patch(f"{_MOD}.trace"),
    ):
        task._schedule_jobs_if_slots_available(  # pylint: disable=protected-access
            max_slots_possible=5, number_of_slots_running=0, gpu_job=False
        )

    mock_job.save_direct.assert_called_once_with(["status", "ray_job_id", "compute_resource"])
