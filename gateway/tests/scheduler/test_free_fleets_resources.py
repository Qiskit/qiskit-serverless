"""Tests for FreeFleetsResources."""

import logging
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
    """A terminal Fleets job that finished `age_hours` ago."""
    kwargs.setdefault("ce_project_name", program.code_engine_project.project_name)
    job = TestUtils.create_job(
        author=program.author,
        program=program,
        status=Job.SUCCEEDED,
        runner=Program.FLEETS,
        fleet_id=fleet_id,
        finished_at=timezone.now() - timedelta(hours=age_hours),
        **kwargs,
    )
    job.refresh_from_db()
    return job


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


def test_an_unavailable_cycle_records_exactly_one_failure(fleets_program):
    _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1)
    task = _make_task()
    unavailable = RunnerRetryableError("unavailable")

    for _ in range(_BREAKER_FAILURES - 1):
        _run(task, error=unavailable)

    _run(task, error=unavailable).assert_called_once()
    _run(task, error=unavailable).assert_not_called()


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


def test_a_paused_region_does_not_fill_the_batch(fleets_program):
    """A paused region's backlog used to take all 20 slots, so no other region was ever cleaned."""
    for n in range(DEFAULT_MAX_DELETES_PER_CYCLE):
        _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 10, fleet_id=f"stuck-{n}", ce_region="us-east")
    healthy = _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1, fleet_id="in-eu", ce_region="eu-de")
    task = _make_task()
    for _ in range(Config.get_int(ConfigKey.FLEETS_BREAKER_FAILURES)):
        task.deleter.record_cycle("us-east", code_engine_answered=False)

    _run(task)

    healthy.refresh_from_db()
    assert healthy.fleet_deleted_at is not None
    assert Job.objects.held_fleets().filter(ce_region="us-east").count() == DEFAULT_MAX_DELETES_PER_CYCLE


def test_a_paused_region_reached_through_the_program_does_not_fill_the_batch(fleets_program):
    """These rows carry no ce_region, so only the program fallback shows they belong to the paused region."""
    for n in range(DEFAULT_MAX_DELETES_PER_CYCLE):
        _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 100 + n, fleet_id=f"legacy-{n}", ce_region=None)
    healthy = _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1, fleet_id="in-eu", ce_region="eu-de")
    task = _make_task()
    assert Job.objects.get(fleet_id="legacy-0").fleet_region == "us-east"
    for _ in range(Config.get_int(ConfigKey.FLEETS_BREAKER_FAILURES)):
        task.deleter.record_cycle("us-east", code_engine_answered=False)

    _run(task)

    healthy.refresh_from_db()
    assert healthy.fleet_deleted_at is not None
    assert Job.objects.held_fleets().filter(ce_region__isnull=True).count() == DEFAULT_MAX_DELETES_PER_CYCLE


def test_the_cap_is_off_when_the_quota_is_zero(fleets_program):
    """quota 0 floors the threshold to 0, which would put every project over it."""
    _force_at(quota=0, percent=80)
    job = _terminal_job(fleets_program, age_hours=1, fleet_id="fleet-1")

    free_resources = _run(_make_task())

    free_resources.assert_not_called()
    job.refresh_from_db()
    assert job.fleet_deleted_at is None


def test_a_clean_cycle_clears_the_delete_failures(fleets_program):
    """Four failures, one cycle that deleted, four more: the streak restarted, so the breaker is closed."""
    _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1, ce_region="us-east")
    task = _make_task()
    threshold = Config.get_int(ConfigKey.FLEETS_BREAKER_FAILURES)

    for _ in range(threshold - 1):
        _run(task, error=RunnerRetryableError("unavailable"))
    _run(task)
    for _ in range(threshold - 1):
        _run(task, error=RunnerRetryableError("unavailable"))

    assert task.deleter.paused("us-east") is False


def test_a_cycle_that_never_reached_code_engine_clears_nothing(fleets_program):
    """A False can be a missing project or a bad host, so it must not pass for a working region."""
    _terminal_job(fleets_program, age_hours=_RETENTION_HOURS + 1, ce_region="us-east")
    task = _make_task()
    threshold = Config.get_int(ConfigKey.FLEETS_BREAKER_FAILURES)

    for _ in range(threshold - 1):
        _run(task, error=RunnerRetryableError("unavailable"))
    _run(task, deleted=False)

    _run(task, error=RunnerRetryableError("unavailable"))

    assert task.deleter.paused("us-east") is True


def test_the_cap_is_off_at_zero_percent(fleets_program):
    """0 would floor the threshold to 0, putting every project over quota and deleting fresh fleets."""
    _force_at(quota=2, percent=0)
    job = _terminal_job(fleets_program, age_hours=1, fleet_id="fleet-1")
    _terminal_job(fleets_program, age_hours=1, fleet_id="fleet-2")

    free_resources = _run(_make_task())

    free_resources.assert_not_called()
    job.refresh_from_db()
    assert job.fleet_deleted_at is None


def test_the_cap_is_off_at_a_hundred_percent(fleets_program):
    _force_at(quota=2, percent=100)
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
    """Threshold 2 of 4 and 5 held: three deletes reach 2, so a whole batch must not destroy more."""
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


def test_the_forced_delete_stops_once_the_project_is_back_under_the_quota(fleets_program):
    """Threshold 2 of 4, three fresh fleets, one delete per cycle: two go and the third stays."""
    _force_at(quota=4, percent=50)
    for n in range(3):
        _terminal_job(fleets_program, age_hours=1, fleet_id=f"fleet-{n}")
    task = _make_task()

    Config.set(ConfigKey.FLEETS_CLEANUP_MAX_DELETES, "1")
    _run(task)
    _run(task)
    free_resources = _run(task)

    free_resources.assert_not_called()
    assert Job.objects.held_fleets().count() == 1


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


def test_logs_an_error_when_a_project_over_the_quota_has_nothing_to_delete(fleets_program, caplog):
    _force_at(quota=4, percent=50)
    for n in range(2):
        running = _terminal_job(fleets_program, age_hours=1, fleet_id=f"fleet-{n}")
        Job.objects.filter(pk=running.id).update(status=Job.RUNNING)

    with caplog.at_level(logging.ERROR):
        _run(_make_task())

    assert "no slot can be freed" in caplog.text
    assert "project=ce-test" in caplog.text


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
