"""Tests for DeleteOldFleets."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from core.config_key import ConfigKey
from core.models import Config, Job, Program
from core.services.runners import RunnerUnavailableError
from scheduler.tasks.delete_old_fleets import DeleteOldFleets, MAX_DELETES_PER_CYCLE
from tests.utils import TestUtils

pytestmark = pytest.mark.django_db

_MOD = "scheduler.tasks.delete_old_fleets"
_RETENTION_HOURS = 48
_BREAKER_FAILURES = 5


def _make_task():
    kill_signal = MagicMock()
    kill_signal.received = False
    return DeleteOldFleets(kill_signal=kill_signal, metrics=MagicMock())


@pytest.fixture
def fleets_program():
    """A Fleets program with a Code Engine project, with the cleanup enabled."""
    Config.add_defaults()
    Config.set(ConfigKey.FLEETS_CLEANUP_ENABLED, "true")
    Config.set(ConfigKey.FLEETS_CLEANUP_RETENTION_HOURS, str(_RETENTION_HOURS))
    Config.set(ConfigKey.FLEETS_BREAKER_FAILURES, str(_BREAKER_FAILURES))
    return TestUtils.create_program(
        program_title="a-function",
        author="function_owner",
        runner=Program.FLEETS,
        code_engine_project=TestUtils.get_or_create_ce_project(
            project_name="ce-test", project_id="ce-id", cos_bucket_user_data_name="test-bucket"
        ),
    )


def _terminal_job(program, *, age_hours, fleet_id="fleet-1", **kwargs):
    """A terminal Fleets job whose last write was `age_hours` ago."""
    kwargs.setdefault("ce_project_name", program.code_engine_project.project_name)
    job = TestUtils.create_job(
        author=program.author,
        program=program,
        status=Job.SUCCEEDED,
        runner=Program.FLEETS,
        fleet_id=fleet_id,
        **kwargs,
    )
    # A queryset update skips auto_now, which is the only way to age the row.
    Job.objects.filter(pk=job.id).update(updated=timezone.now() - timedelta(hours=age_hours))
    return job


def _run(task, *, deleted=True, error=None):
    with patch(f"{_MOD}.get_runner") as get_runner:
        if error:
            get_runner.return_value.free_resources.side_effect = error
        else:
            get_runner.return_value.free_resources.return_value = deleted
        task.run()
    return get_runner.return_value.free_resources


def test_deletes_the_fleet_and_stamps_the_job_past_the_window(fleets_program):
    job = _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1)

    free_resources = _run(_make_task())

    free_resources.assert_called_once()
    job.refresh_from_db()
    assert job.fleet_deleted_at is not None
    assert job.fleet_id == "fleet-1"


def test_does_not_delete_a_fleet_twice(fleets_program):
    _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1)
    task = _make_task()

    _run(task)
    free_resources = _run(task)

    free_resources.assert_not_called()


def test_keeps_a_fleet_inside_the_window(fleets_program):
    job = _terminal_job(fleets_program, age_hours=_RETENTION_HOURS - 1)

    free_resources = _run(_make_task())

    free_resources.assert_not_called()
    job.refresh_from_db()
    assert job.fleet_deleted_at is None


def test_does_not_stamp_when_the_delete_fails(fleets_program):
    job = _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1)

    free_resources = _run(_make_task(), deleted=False)

    free_resources.assert_called_once()
    job.refresh_from_db()
    assert job.fleet_deleted_at is None


def test_does_nothing_while_disabled_but_still_reports(fleets_program):
    Config.set(ConfigKey.FLEETS_CLEANUP_ENABLED, "false")
    job = _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1)
    task = _make_task()

    free_resources = _run(task)

    free_resources.assert_not_called()
    job.refresh_from_db()
    assert job.fleet_deleted_at is None
    task.metrics.set_held_fleets.assert_called_once_with(1, "ce-test")


def test_keeps_a_stopping_job(fleets_program):
    job = _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1)
    Job.objects.filter(pk=job.id).update(status=Job.STOPPING)

    free_resources = _run(_make_task())

    free_resources.assert_not_called()


def test_reports_every_held_fleet_per_project_whatever_the_status(fleets_program):
    _terminal_job(fleets_program, age_hours=1, fleet_id="fleet-1")
    running = _terminal_job(fleets_program, age_hours=1, fleet_id="fleet-2")
    Job.objects.filter(pk=running.id).update(status=Job.RUNNING)
    task = _make_task()

    _run(task)

    task.metrics.set_held_fleets.assert_called_once_with(2, "ce-test")


def test_reports_against_the_project_the_job_ran_in(fleets_program):
    _terminal_job(fleets_program, age_hours=1, ce_project_name="old-project")
    task = _make_task()

    _run(task)

    task.metrics.set_held_fleets.assert_called_once_with(1, "old-project")


def test_reports_the_held_fleets_once_per_report_window(fleets_program):
    _terminal_job(fleets_program, age_hours=1)
    task = _make_task()

    _run(task)
    _run(task)

    task.metrics.set_held_fleets.assert_called_once()


def test_a_rate_limit_ends_the_cycle_after_one_call(fleets_program):
    _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 2, fleet_id="fleet-1")
    _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1, fleet_id="fleet-2")

    free_resources = _run(_make_task(), error=RunnerUnavailableError("unavailable"))

    free_resources.assert_called_once()


def test_a_whole_failed_batch_opens_the_breaker(fleets_program):
    _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1)
    task = _make_task()

    for _ in range(_BREAKER_FAILURES):
        _run(task, deleted=False)

    free_resources = _run(task, deleted=False)
    free_resources.assert_not_called()


def test_a_partly_failed_batch_is_not_a_failure(fleets_program):
    _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 2, fleet_id="broken")
    _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1, fleet_id="fine")
    task = _make_task()

    with patch(f"{_MOD}.get_runner") as get_runner:
        get_runner.return_value.free_resources.side_effect = [False, True]
        task.run()

    assert Job.objects.filter(fleet_id="fine", fleet_deleted_at__isnull=False).exists()
    assert Job.objects.filter(fleet_id="broken", fleet_deleted_at__isnull=True).exists()


def test_deletes_at_most_one_batch_per_cycle(fleets_program):
    for index in range(MAX_DELETES_PER_CYCLE + 1):
        _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1, fleet_id=f"fleet-{index}")

    free_resources = _run(_make_task())

    assert free_resources.call_count == MAX_DELETES_PER_CYCLE
