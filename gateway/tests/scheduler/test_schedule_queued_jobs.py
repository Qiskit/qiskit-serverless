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

"""Unit tests for ScheduleQueuedJobs."""

from unittest.mock import MagicMock, patch, call

import pytest
from concurrency.exceptions import RecordModifiedError

from scheduler.tasks.schedule_queued_jobs import ScheduleQueuedJobs

_MOD = "scheduler.tasks.schedule_queued_jobs"


def _make_task():
    kill_signal = MagicMock()
    kill_signal.received = False
    return ScheduleQueuedJobs(kill_signal=kill_signal, metrics=MagicMock())


def test_fleet_id_preserved_on_record_modified_error_retry():
    """fleet_id set by execute_job is restored after RecordModifiedError + refresh_from_db."""
    task = _make_task()

    mock_job = MagicMock()
    mock_job.fleet_id = "fleet-abc"
    mock_job.status = "PENDING"
    mock_job.logs = ""
    mock_job.compute_resource = None
    mock_job.ray_job_id = None
    mock_job.env_vars = '{"traceparent": null}'

    # First save raises RecordModifiedError; refresh_from_db wipes fleet_id; second save succeeds.
    save_calls = [RecordModifiedError(target=mock_job), None]
    mock_job.save.side_effect = save_calls

    def fake_refresh():
        mock_job.fleet_id = None  # simulates DB reload clearing the unsaved fleet_id

    mock_job.refresh_from_db.side_effect = fake_refresh

    with (
        patch(f"{_MOD}.get_jobs_to_schedule_fair_share", return_value=[mock_job]),
        patch(f"{_MOD}.execute_job", return_value=mock_job),
        patch(f"{_MOD}.settings") as mock_settings,
        patch(f"{_MOD}.JobEvent"),
        patch(f"{_MOD}.TraceContextTextMapPropagator"),
        patch(f"{_MOD}.trace"),
    ):
        mock_settings.RAY_SETUP_MAX_RETRIES = 3
        mock_settings.LIMITS_MAX_FLEETS = 10
        mock_settings.LIMITS_JOBS_PER_USER = 5
        task._schedule_jobs_if_slots_available(  # pylint: disable=protected-access
            max_slots_possible=5, number_of_slots_running=0, gpu_job=False
        )

    assert mock_job.fleet_id == "fleet-abc"
