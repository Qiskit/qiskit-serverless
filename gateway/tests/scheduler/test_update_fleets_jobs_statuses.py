"""Unit tests for UpdateFleetsJobsStatuses."""

from unittest.mock import MagicMock, patch

from core.models import Job, Program
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
    job.in_terminal_state.return_value = False
    job.SUCCEEDED = Job.SUCCEEDED
    job.FAILED = Job.FAILED
    return job


class TestFleetsJobStatusUpdate:
    """Tests for UpdateFleetsJobsStatuses.update_job_status()."""

    def test_result_retrieved_from_cos_on_terminal_state(self):
        """Saves COS result to job.result when Fleets job reaches terminal state."""
        task = _make_task()
        job = _make_fleets_job()
        job.in_terminal_state.return_value = True

        mock_runner = MagicMock()
        mock_runner.status.return_value = Job.SUCCEEDED
        mock_runner.get_result_from_cos.return_value = '{"counts": {"00": 512}}'

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch(f"{_MOD}.JobEvent"),
        ):
            task.update_job_status(job)

        mock_runner.get_result_from_cos.assert_called_once()
        assert job.result == '{"counts": {"00": 512}}'

    def test_result_skipped_when_cos_returns_none(self):
        """Leaves job.result unchanged when get_result_from_cos returns None."""
        task = _make_task()
        job = _make_fleets_job()
        job.in_terminal_state.return_value = True
        job.result = "previous-result"

        mock_runner = MagicMock()
        mock_runner.status.return_value = Job.SUCCEEDED
        mock_runner.get_result_from_cos.return_value = None

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch(f"{_MOD}.JobEvent"),
        ):
            task.update_job_status(job)

        assert job.result == "previous-result"

    def test_cos_error_is_swallowed(self):
        """Logs a warning and continues if get_result_from_cos raises."""
        task = _make_task()
        job = _make_fleets_job()
        job.in_terminal_state.return_value = True

        mock_runner = MagicMock()
        mock_runner.status.return_value = Job.SUCCEEDED
        mock_runner.get_result_from_cos.side_effect = RuntimeError("COS unavailable")

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch(f"{_MOD}.JobEvent"),
        ):
            task.update_job_status(job)  # should not raise
