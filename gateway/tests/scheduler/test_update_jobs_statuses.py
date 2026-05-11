# This code is part of a Qiskit project.
#
# (C) IBM 2026
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Unit tests for UpdateJobsStatuses."""

from unittest.mock import MagicMock, patch

from core.models import Job, Program
from scheduler.tasks.update_jobs_statuses import UpdateJobsStatuses

_MOD = "scheduler.tasks.update_jobs_statuses"


def _make_task():
    kill_signal = MagicMock()
    kill_signal.received = False
    return UpdateJobsStatuses(kill_signal=kill_signal, metrics=MagicMock())


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


def _make_ray_job(status=Job.RUNNING):
    job = MagicMock(spec=Job)
    job.runner = Program.RAY
    job.compute_resource = MagicMock()
    job.gpu = False
    job.status = status
    job.logs = ""
    job.env_vars = "{}"
    job.sub_status = None
    job.in_terminal_state.return_value = False
    job.SUCCEEDED = Job.SUCCEEDED
    job.FAILED = Job.FAILED
    return job


class TestFleetsJobStatusUpdate:
    """Tests for update_job_status() with Fleets jobs."""


class TestRayJobStatusUpdate:
    """Tests for update_job_status() with Ray jobs."""

    def test_logs_fetched_once_on_terminal_state(self):
        """runner.logs() is called exactly once when a Ray job transitions to a terminal state.

        Regression test: before the fix, logs were fetched twice — once in the terminal-state
        handler (to save them) and again unconditionally for the "no resources" check, doubling
        peak memory usage and causing OOM on large log payloads.
        """
        task = _make_task()
        job = _make_ray_job()
        job.in_terminal_state.return_value = True

        mock_runner = MagicMock()
        mock_runner.status.return_value = Job.SUCCEEDED
        mock_runner.logs.return_value = "some logs"

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch(f"{_MOD}.check_job_timeout", return_value=False),
            patch(f"{_MOD}.save_logs_to_storage"),
            patch(f"{_MOD}.Job.objects"),
            patch(f"{_MOD}.JobEvent"),
        ):
            task.update_job_status(job)

        assert mock_runner.logs.call_count == 1

    def test_logs_fetched_for_running_job(self):
        """runner.logs() is called once for a still-RUNNING Ray job (the "no resources" check)."""
        task = _make_task()
        job = _make_ray_job()
        job.in_terminal_state.return_value = False

        mock_runner = MagicMock()
        mock_runner.status.return_value = Job.RUNNING
        mock_runner.logs.return_value = "some logs"

        with (
            patch(f"{_MOD}.get_runner", return_value=mock_runner),
            patch(f"{_MOD}.check_job_timeout", return_value=False),
            patch(f"{_MOD}.Job.objects"),
            patch(f"{_MOD}.JobEvent"),
        ):
            task.update_job_status(job)

        assert mock_runner.logs.call_count == 1
