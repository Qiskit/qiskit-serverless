"""Tests for FreeFleetsResources."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from core.config_key import ConfigKey
from core.models import Config, Job, Program
from core.services.runners import RunnerRetryableError
from scheduler.tasks.free_fleets_resources import (
    FreeFleetsResources,
    MAX_ATTEMPTS_PER_FLEET,
    DEFAULT_MAX_DELETES_PER_CYCLE,
    MAX_TRACKED_FAILURES,
)
from tests.utils import TestUtils

pytestmark = pytest.mark.django_db

_SCHEDULE_MOD = "scheduler.schedule"
_TASK_MOD = "scheduler.tasks.free_fleets_resources"
_RETENTION_HOURS = 48
_BREAKER_FAILURES = 5


def _make_task():
    kill_signal = MagicMock()
    kill_signal.received = False
    return FreeFleetsResources(kill_signal=kill_signal, metrics=MagicMock())


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
    _age(job, age_hours)
    return job


def _age(job, age_hours):
    """Move a job's `updated` back. A queryset update skips auto_now, which is the only way."""
    Job.objects.filter(pk=job.id).update(updated=timezone.now() - timedelta(hours=age_hours))
    job.refresh_from_db()


def _run(task, *, deleted=True, error=None):
    with patch(f"{_SCHEDULE_MOD}.get_runner") as get_runner:
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
    job = _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1)
    task = _make_task()

    _run(task)
    _age(job, _RETENTION_HOURS + 1)
    free_resources = _run(task)

    free_resources.assert_not_called()


def test_keeps_a_fleet_inside_the_window(fleets_program):
    job = _terminal_job(fleets_program, age_hours=_RETENTION_HOURS - 1)

    free_resources = _run(_make_task())

    free_resources.assert_not_called()
    job.refresh_from_db()
    assert job.fleet_deleted_at is None


def test_does_not_stamp_a_fleet_it_could_not_delete(fleets_program):
    job = _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1)

    free_resources = _run(_make_task(), deleted=False)

    free_resources.assert_called_once()
    job.refresh_from_db()
    assert job.fleet_deleted_at is None


def test_gives_up_on_a_fleet_after_three_attempts(fleets_program):
    _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 2, fleet_id="broken")
    task = _make_task()

    for _ in range(MAX_ATTEMPTS_PER_FLEET):
        _run(task, deleted=False)

    _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1, fleet_id="fine")
    free_resources = _run(task, deleted=True)

    assert free_resources.call_count == 1
    assert Job.objects.filter(fleet_id="fine", fleet_deleted_at__isnull=False).exists()
    assert Job.objects.filter(fleet_id="broken", fleet_deleted_at__isnull=True).exists()


def test_counting_new_failures_does_not_forget_a_fleet_already_given_up_on(fleets_program, monkeypatch):
    monkeypatch.setattr(f"{_TASK_MOD}.MAX_TRACKED_FAILURES", 2)
    task = _make_task()
    broken = _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 5, fleet_id="broken")
    for _ in range(MAX_ATTEMPTS_PER_FLEET):
        _run(task, deleted=False)
    for n in range(3):
        task._count_failure(
            _terminal_job(fleets_program, age_hours=1, fleet_id=f"new-{n}")
        )  # pylint: disable=protected-access

    assert str(broken.id) in task._giving_up_on()  # pylint: disable=protected-access


def test_the_oldest_fleet_given_up_on_is_the_one_forgotten(fleets_program, monkeypatch):
    monkeypatch.setattr(f"{_TASK_MOD}.MAX_TRACKED_FAILURES", 3)
    task = _make_task()
    jobs = [_terminal_job(fleets_program, age_hours=1, fleet_id=f"broken-{n}") for n in range(4)]
    for job in jobs:
        for _ in range(MAX_ATTEMPTS_PER_FLEET):
            task._count_failure(job)  # pylint: disable=protected-access

    assert task._giving_up_on() == [str(job.id) for job in jobs[1:]]  # pylint: disable=protected-access


def test_does_nothing_while_disabled_but_still_reports(fleets_program):
    Config.set(ConfigKey.FLEETS_CLEANUP_ENABLED, "false")
    job = _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1)
    task = _make_task()

    free_resources = _run(task)

    free_resources.assert_not_called()
    job.refresh_from_db()
    assert job.fleet_deleted_at is None
    task.metrics.set_held_fleets.assert_called_once_with(1, "ce-test")


def test_a_broken_metrics_report_does_not_stop_the_deletes(fleets_program):
    job = _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1)
    task = _make_task()
    task.metrics.clear_held_fleets.side_effect = RuntimeError("prometheus is unhappy")

    free_resources = _run(task)

    free_resources.assert_called_once()
    job.refresh_from_db()
    assert job.fleet_deleted_at is not None


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


def test_an_unavailable_engine_ends_the_cycle_after_one_call(fleets_program):
    _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 2, fleet_id="fleet-1")
    _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1, fleet_id="fleet-2")

    free_resources = _run(_make_task(), error=RunnerRetryableError("unavailable"))

    free_resources.assert_called_once()


def test_a_cycle_that_stopped_on_a_rate_limit_is_a_failure(fleets_program):
    for index in range(2 * _BREAKER_FAILURES):
        _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + index + 1, fleet_id=f"fleet-{index}")
    task = _make_task()

    for _ in range(_BREAKER_FAILURES):
        with patch(f"{_SCHEDULE_MOD}.get_runner") as get_runner:
            get_runner.return_value.free_resources.side_effect = [True, RunnerRetryableError("429")]
            task.run()

    free_resources = _run(task)
    free_resources.assert_not_called()


def test_the_attempt_counts_stay_bounded(fleets_program):
    _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1)
    task = _make_task()
    task._failed_attempts = {f"old-{n}": 1 for n in range(MAX_TRACKED_FAILURES)}  # pylint: disable=protected-access

    _run(task, deleted=False)

    assert len(task._failed_attempts) == MAX_TRACKED_FAILURES  # pylint: disable=protected-access


def test_deletes_one_fleet_and_stops_once_the_time_budget_is_spent(fleets_program):
    Config.set(ConfigKey.FLEETS_CLEANUP_BUDGET_MS, "0")
    for n in range(3):
        _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + n + 1, fleet_id=f"fleet-{n}")

    free_resources = _run(_make_task())

    free_resources.assert_called_once()
    assert Job.objects.held_fleets().count() == 2


def test_deletes_at_most_one_batch_per_cycle(fleets_program):
    for index in range(DEFAULT_MAX_DELETES_PER_CYCLE + 1):
        _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1, fleet_id=f"fleet-{index}")

    free_resources = _run(_make_task())

    assert free_resources.call_count == DEFAULT_MAX_DELETES_PER_CYCLE


def test_a_failed_region_does_not_stop_the_other_regions(fleets_program):
    _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 2, fleet_id="in-us", ce_region="us-east")
    healthy = _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1, fleet_id="in-eu", ce_region="eu-de")

    with patch(f"{_SCHEDULE_MOD}.get_runner") as get_runner:
        get_runner.return_value.free_resources.side_effect = [RunnerRetryableError("unavailable"), True]
        _make_task().run()

    healthy.refresh_from_db()
    assert healthy.fleet_deleted_at is not None


@pytest.mark.parametrize("ce_region", [None, ""])
def test_a_paused_region_reached_through_the_program_does_not_fill_the_batch(fleets_program, ce_region):
    for n in range(DEFAULT_MAX_DELETES_PER_CYCLE):
        _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 100 + n, fleet_id=f"legacy-{n}", ce_region=ce_region)
    healthy = _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1, fleet_id="in-eu", ce_region="eu-de")
    task = _make_task()
    assert Job.objects.get(fleet_id="legacy-0").fleet_region == "us-east"
    for _ in range(_BREAKER_FAILURES):
        task.deleter.record_cycle("us-east", answered=False)

    _run(task)

    healthy.refresh_from_db()
    assert healthy.fleet_deleted_at is not None
    assert Job.objects.held_fleets().filter(fleet_id__startswith="legacy-").count() == DEFAULT_MAX_DELETES_PER_CYCLE


def test_a_clean_cycle_clears_the_delete_failures(fleets_program):
    _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1, fleet_id="first", ce_region="us-east")
    second = _terminal_job(fleets_program, age_hours=1, fleet_id="second", ce_region="us-east")
    task = _make_task()
    threshold = _BREAKER_FAILURES

    for _ in range(threshold - 1):
        _run(task, error=RunnerRetryableError("unavailable"))
    _run(task)
    # the deleted fleet leaves the window, so without a second candidate the cycles below record nothing
    _age(second, _RETENTION_HOURS + 1)
    for _ in range(threshold - 1):
        _run(task, error=RunnerRetryableError("unavailable"))

    assert task.deleter.paused("us-east") is False


def test_a_cycle_that_never_reached_code_engine_clears_nothing(fleets_program):
    _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1, ce_region="us-east")
    task = _make_task()
    threshold = _BREAKER_FAILURES

    for _ in range(threshold - 1):
        _run(task, error=RunnerRetryableError("unavailable"))
    _run(task, deleted=False)

    _run(task, error=RunnerRetryableError("unavailable"))

    assert task.deleter.paused("us-east") is True


@pytest.mark.parametrize("quota, percent", [(0, 80), (2, 0), (2, 100)])
def test_the_cap_is_off_outside_its_range(fleets_program, quota, percent):
    _force_at(quota=quota, percent=percent)
    job = _terminal_job(fleets_program, age_hours=1, fleet_id="fleet-1")
    _terminal_job(fleets_program, age_hours=1, fleet_id="fleet-2")

    free_resources = _run(_make_task())

    free_resources.assert_not_called()
    job.refresh_from_db()
    assert job.fleet_deleted_at is None


def _force_at(*, quota, percent):
    Config.set(ConfigKey.FLEETS_QUOTA_PER_PROJECT, str(quota))
    Config.set(ConfigKey.FLEETS_CLEANUP_FORCE_AT_PERCENT, str(percent))


def test_deletes_a_fleet_inside_the_window_when_its_project_is_over_the_quota(fleets_program):
    _force_at(quota=4, percent=50)
    oldest = _terminal_job(fleets_program, age_hours=2, fleet_id="fleet-1")
    newest = _terminal_job(fleets_program, age_hours=1, fleet_id="fleet-2")

    free_resources = _run(_make_task())

    free_resources.assert_called_once()
    oldest.refresh_from_db()
    newest.refresh_from_db()
    assert oldest.fleet_deleted_at is not None
    assert newest.fleet_deleted_at is None


def test_a_retention_backlog_does_not_starve_the_quota_cap(fleets_program):
    _force_at(quota=4, percent=50)
    for n in range(DEFAULT_MAX_DELETES_PER_CYCLE):
        _terminal_job(
            fleets_program, age_hours=_RETENTION_HOURS + 100 + n, fleet_id=f"old-{n}", ce_project_name="quiet-project"
        )
    urgent = _terminal_job(fleets_program, age_hours=1, fleet_id="urgent-1", ce_project_name="busy-project")
    _terminal_job(fleets_program, age_hours=1, fleet_id="urgent-2", ce_project_name="busy-project")

    _run(_make_task())

    urgent.refresh_from_db()
    assert urgent.fleet_deleted_at is not None


def test_the_cap_takes_no_more_than_the_project_needs(fleets_program):
    _force_at(quota=4, percent=50)
    for n in range(5):
        _terminal_job(fleets_program, age_hours=n + 1, fleet_id=f"fleet-{n}")

    free_resources = _run(_make_task())

    assert free_resources.call_count == 4
    assert Job.objects.held_fleets().count() == 1


def test_only_the_project_over_the_quota_loses_its_fresh_fleets(fleets_program):
    _force_at(quota=4, percent=50)
    busy = _terminal_job(fleets_program, age_hours=1, fleet_id="fleet-1")
    _terminal_job(fleets_program, age_hours=1, fleet_id="fleet-2")
    quiet = _terminal_job(fleets_program, age_hours=1, fleet_id="fleet-3", ce_project_name="quiet-project")

    _run(_make_task())

    busy.refresh_from_db()
    quiet.refresh_from_db()
    assert busy.fleet_deleted_at is not None
    assert quiet.fleet_deleted_at is None


def test_never_deletes_a_running_fleet_even_at_the_full_quota(fleets_program):
    _force_at(quota=4, percent=50)
    running = _terminal_job(fleets_program, age_hours=1, fleet_id="fleet-running")
    Job.objects.filter(pk=running.id).update(status=Job.RUNNING)
    terminal = _terminal_job(fleets_program, age_hours=1, fleet_id="fleet-terminal")

    free_resources = _run(_make_task())

    free_resources.assert_called_once()
    running.refresh_from_db()
    terminal.refresh_from_db()
    assert running.fleet_deleted_at is None
    assert terminal.fleet_deleted_at is not None


def test_fleets_without_a_project_do_not_trip_the_quota(fleets_program):
    _force_at(quota=4, percent=50)
    unassigned = [
        _terminal_job(fleets_program, age_hours=1, fleet_id=f"fleet-{n}", ce_project_name="") for n in range(3)
    ]
    busy = _terminal_job(fleets_program, age_hours=1, fleet_id="busy-1", ce_project_name="busy-project")
    _terminal_job(fleets_program, age_hours=1, fleet_id="busy-2", ce_project_name="busy-project")

    _run(_make_task())

    busy.refresh_from_db()
    assert busy.fleet_deleted_at is not None
    for job in unassigned:
        job.refresh_from_db()
        assert job.fleet_deleted_at is None
