"""Unit tests for UpdateJobStatusCounts."""

from unittest.mock import MagicMock, patch, call

from scheduler.tasks.update_job_status_counts import UpdateJobStatusCounts

_MOD = "scheduler.tasks.update_job_status_counts"


def _make_task():
    kill_signal = MagicMock()
    kill_signal.received = False
    return UpdateJobStatusCounts(kill_signal=kill_signal, metrics=MagicMock())


def test_job_status_counts_clears_and_sets_metrics():
    """run() clears existing counts then sets one entry per (status, provider) pair."""
    task = _make_task()

    fake_rows = [
        {"status": "QUEUED", "program__provider__name": "ibm", "count": 3},
        {"status": "RUNNING", "program__provider__name": None, "count": 1},
    ]

    with patch(f"{_MOD}.Job") as MockJob:
        MockJob.QUEUED = "QUEUED"
        MockJob.PENDING = "PENDING"
        MockJob.RUNNING = "RUNNING"
        MockJob.objects.filter.return_value.values.return_value.annotate.return_value = fake_rows
        task.run()

    task.metrics.clear_job_status_counts.assert_called_once()
    task.metrics.set_job_status_count.assert_any_call(3, "QUEUED", "ibm")
    task.metrics.set_job_status_count.assert_any_call(1, "RUNNING", "custom")
