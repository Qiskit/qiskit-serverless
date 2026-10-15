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
    """Re-aged between the cycles, so only fleet_deleted_at can keep it out of the second one."""
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
    """A row that keeps failing must stop consuming a slot in the batch."""
    _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 2, fleet_id="broken")
    task = _make_task()

    for _ in range(MAX_ATTEMPTS_PER_FLEET):
        _run(task, deleted=False)

    _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1, fleet_id="fine")
    free_resources = _run(task, deleted=True)

    assert free_resources.call_count == 1
    assert Job.objects.filter(fleet_id="fine", fleet_deleted_at__isnull=False).exists()
    assert Job.objects.filter(fleet_id="broken", fleet_deleted_at__isnull=True).exists()


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
    """Sustained partial rate limiting has to open the breaker instead of oscillating for ever."""
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
    """The scheduler is one long-lived replica, so a permanently failing fleet must not grow the dict."""
    _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1)
    task = _make_task()
    task._failed_attempts = {f"old-{n}": 1 for n in range(MAX_TRACKED_FAILURES)}  # pylint: disable=protected-access

    _run(task, deleted=False)

    assert len(task._failed_attempts) == MAX_TRACKED_FAILURES  # pylint: disable=protected-access


def test_stops_when_the_time_budget_is_spent(fleets_program):
    """Each delete costs a Code Engine round trip and the scheduler loop is single threaded."""
    for n in range(3):
        _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + n + 1, fleet_id=f"fleet-{n}")

    with patch(f"{_TASK_MOD}.time.monotonic", side_effect=[0, 999]):
        free_resources = _run(_make_task())

    free_resources.assert_called_once()
    assert Job.objects.held_fleets().count() == 2


def test_always_deletes_one_even_with_no_budget(fleets_program):
    """Otherwise a cycle whose queries are slow would make no progress at all, for ever."""
    Config.set(ConfigKey.FLEETS_CLEANUP_BUDGET_MS, "0")
    for n in range(3):
        _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + n + 1, fleet_id=f"fleet-{n}")

    free_resources = _run(_make_task())

    free_resources.assert_called_once()


def test_deletes_at_most_one_batch_per_cycle(fleets_program):
    for index in range(DEFAULT_MAX_DELETES_PER_CYCLE + 1):
        _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1, fleet_id=f"fleet-{index}")

    free_resources = _run(_make_task())

    assert free_resources.call_count == DEFAULT_MAX_DELETES_PER_CYCLE


def test_a_failed_region_does_not_stop_the_other_regions(fleets_program):
    """Without the per-region skip, one bad region stalls every project's cleanup."""
    _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 2, fleet_id="in-us", ce_region="us-east")
    healthy = _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1, fleet_id="in-eu", ce_region="eu-de")

    with patch(f"{_SCHEDULE_MOD}.get_runner") as get_runner:
        get_runner.return_value.free_resources.side_effect = [RunnerRetryableError("unavailable"), True]
        _make_task().run()

    healthy.refresh_from_db()
    assert healthy.fleet_deleted_at is not None


def test_a_paused_region_reached_through_the_program_does_not_fill_the_batch(fleets_program):
    """These rows carry no ce_region, so only the program fallback shows they belong to the paused region."""
    for n in range(DEFAULT_MAX_DELETES_PER_CYCLE):
        _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 100 + n, fleet_id=f"legacy-{n}", ce_region=None)
    healthy = _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1, fleet_id="in-eu", ce_region="eu-de")
    task = _make_task()
    assert Job.objects.get(fleet_id="legacy-0").fleet_region == "us-east"
    for _ in range(_BREAKER_FAILURES):
        task.deleter.record_cycle("us-east", code_engine_answered=False)

    _run(task)

    healthy.refresh_from_db()
    assert healthy.fleet_deleted_at is not None
    assert Job.objects.held_fleets().filter(ce_region__isnull=True).count() == DEFAULT_MAX_DELETES_PER_CYCLE


def test_a_clean_cycle_clears_the_delete_failures(fleets_program):
    """Four failures, one cycle that deleted, four more: the streak restarted, so the breaker is closed."""
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
    """A False can be a missing project or a bad host, so it must not pass for a working region."""
    _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1, ce_region="us-east")
    task = _make_task()
    threshold = _BREAKER_FAILURES

    for _ in range(threshold - 1):
        _run(task, error=RunnerRetryableError("unavailable"))
    _run(task, deleted=False)

    _run(task, error=RunnerRetryableError("unavailable"))

    assert task.deleter.paused("us-east") is True


def test_an_empty_region_falls_back_like_a_null_one(fleets_program):
    """The admin can save ce_region as "", and Coalesce alone would read that as the region."""
    for n in range(DEFAULT_MAX_DELETES_PER_CYCLE):
        _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 100 + n, fleet_id=f"blank-{n}", ce_region="")
    healthy = _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1, fleet_id="in-eu", ce_region="eu-de")
    task = _make_task()
    for _ in range(_BREAKER_FAILURES):
        task.deleter.record_cycle("us-east", code_engine_answered=False)

    _run(task)

    healthy.refresh_from_db()
    assert healthy.fleet_deleted_at is not None


@pytest.mark.parametrize("quota, percent", [(0, 80), (2, 0), (2, 100)])
def test_the_cap_is_off_outside_its_range(fleets_program, quota, percent):
    """A threshold of 0 would put every project over quota, and 100 means the window is the only rule."""
    _force_at(quota=quota, percent=percent)
    job = _terminal_job(fleets_program, age_hours=1, fleet_id="fleet-1")
    _terminal_job(fleets_program, age_hours=1, fleet_id="fleet-2")

    free_resources = _run(_make_task())

    free_resources.assert_not_called()
    job.refresh_from_db()
    assert job.fleet_deleted_at is None


def _force_at(*, quota, percent):
    """Make the quota cap trip at `quota * percent / 100` held fleets in one project."""
    Config.set(ConfigKey.FLEETS_QUOTA_PER_PROJECT, str(quota))
    Config.set(ConfigKey.FLEETS_CLEANUP_FORCE_AT_PERCENT, str(percent))


def test_deletes_a_fleet_inside_the_window_when_its_project_is_over_the_quota(fleets_program):
    """Threshold 2 of 4 and 2 held: it needs one delete to get under, so only the oldest goes."""
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
    """The over-quota fleets are the newest, so one shared ordering would always serve the backlog first."""
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
    """Threshold 2 of 4 and 5 held: four deletes get it under 2, so a whole batch must not destroy more."""
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
    """Over the quota, the terminal fleet goes and the running one stays, because deleting it kills the job."""
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
    """Three unassigned fleets would be over the threshold of 2, but they count against no project."""
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
