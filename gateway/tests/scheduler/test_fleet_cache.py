"""Tests for FleetCache."""

from concurrent.futures import Future
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from core.models import Job, Program
from core.services.runners import RunnerError, RunnerRetryableError
from scheduler.fleet_cache import (
    CHECK_EVERY_SECONDS,
    LIST_EVERY_SECONDS,
    LIST_MAX_AGE_SECONDS,
    STUCK_AFTER_SECONDS,
    FleetCache,
)
from tests.utils import TestUtils

pytestmark = pytest.mark.django_db

_PROJECT = "ce-test"
_THRESHOLD = 3


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _run_now(fn, *args, replace_key=None):  # pylint: disable=unused-argument
    future = Future()
    fn(*args)
    future.set_result(None)
    return future


def _cache(listed=None, exists=True, list_error=None):
    deleter = MagicMock()
    deleter.paused.return_value = False
    deleter.handler.return_value = (MagicMock(project_id="ce-id"), "us-east")
    deleter.list_fleets.side_effect = list_error or (lambda handler, region, deadline: dict(listed or {}))
    deleter.fleet_exists.side_effect = exists if callable(exists) else (lambda handler, region, fleet_id: exists)
    clock = _Clock()
    return FleetCache(deleter, submit=_run_now, has_room=lambda: True, clock=clock), deleter, clock


@pytest.fixture(name="program")
def program_fixture():
    return TestUtils.create_program(
        program_title="a-function",
        author="function_owner",
        runner=Program.FLEETS,
        code_engine_project=TestUtils.get_or_create_ce_project(project_name=_PROJECT, project_id="ce-id"),
    )


def _job(program, fleet_id, status=Job.SUCCEEDED, age_hours=1):
    job = TestUtils.create_job(
        author=program.author,
        program=program,
        status=status,
        runner=Program.FLEETS,
        fleet_id=fleet_id,
        ce_project_name=_PROJECT,
    )
    Job.objects.filter(pk=job.id).update(updated=timezone.now() - timedelta(hours=age_hours))
    return job


def test_counts_every_listed_fleet_and_the_deleting_ones_use_the_quota(program):
    for n in range(4):
        _job(program, f"fleet-{n}")
    cache, _, _ = _cache({"fleet-0": "standby", "fleet-1": "standby", "fleet-2": "deleting", "fleet-3": "standby"})

    cache.refresh([_PROJECT])

    assert cache.need(_PROJECT, _THRESHOLD, Job.objects.held_fleets().count()) == 1
    assert cache.alive(_PROJECT) == {"fleet-0", "fleet-1", "fleet-3"}


def test_no_need_without_a_fresh_list(program):
    for n in range(4):
        _job(program, f"fleet-{n}")
    cache, _, clock = _cache({f"fleet-{n}": "standby" for n in range(4)})
    assert cache.need(_PROJECT, _THRESHOLD, Job.objects.held_fleets().count()) == 0

    cache.refresh([_PROJECT])
    clock.now += LIST_MAX_AGE_SECONDS + 1

    assert cache.need(_PROJECT, _THRESHOLD, Job.objects.held_fleets().count()) == 0


def test_a_stale_row_counts_only_once_a_get_finds_its_fleet(program):
    for n in range(4):
        _job(program, f"fleet-{n}")
    cache, deleter, _ = _cache({"fleet-0": "standby"}, exists=lambda handler, region, fleet_id: fleet_id == "fleet-1")

    cache.refresh([_PROJECT])

    assert deleter.fleet_exists.call_count == 3
    assert cache.need(_PROJECT, _THRESHOLD, Job.objects.held_fleets().count()) == 0
    assert Job.objects.held_fleets().count() == 2


def test_a_stale_row_already_deleted_in_code_engine_is_stamped_with_an_event(program):
    job = _job(program, "deleted")
    cache, _, _ = _cache({}, exists=False)

    cache.refresh([_PROJECT])

    job.refresh_from_db()
    assert job.fleet_deleted_at is not None
    assert job.job_events.get(event_type="FLEET_DELETED").data == {"fleet_id": "deleted", "reason": "found_deleted"}


def test_a_new_fleet_counts_without_a_get(program):
    _job(program, "running", status=Job.RUNNING)
    _job(program, "fleet-0")
    _job(program, "fleet-1")
    cache, deleter, _ = _cache({"fleet-0": "standby", "fleet-1": "standby"})

    cache.refresh([_PROJECT])

    deleter.fleet_exists.assert_not_called()
    assert cache.need(_PROJECT, _THRESHOLD, Job.objects.held_fleets().count()) == 1


def test_the_cap_spends_its_need_once_while_the_fleets_delete(program):
    for n in range(5):
        _job(program, f"fleet-{n}")
    cache, _, _ = _cache({f"fleet-{n}": "standby" for n in range(5)})
    cache.refresh([_PROJECT])
    assert cache.need(_PROJECT, _THRESHOLD, Job.objects.held_fleets().count()) == 3

    for n in range(3):
        cache.record_delete(_PROJECT, "job", f"fleet-{n}", "over_quota")

    assert cache.need(_PROJECT, _THRESHOLD, Job.objects.held_fleets().count()) == 0
    assert cache.deleting() == {"fleet-0", "fleet-1", "fleet-2"}


def test_a_deleting_fleet_gets_a_get_every_30_seconds_until_its_404(program):
    job = _job(program, "fleet-0")
    answers = iter([True, False])
    cache, deleter, clock = _cache({"fleet-0": "standby"}, exists=lambda handler, region, fleet_id: next(answers))
    cache.refresh([_PROJECT])
    cache.record_delete(_PROJECT, str(job.id), "fleet-0", "retention")

    cache.refresh([_PROJECT])
    deleter.fleet_exists.assert_not_called()

    clock.now += CHECK_EVERY_SECONDS
    cache.refresh([_PROJECT])
    clock.now += CHECK_EVERY_SECONDS
    cache.refresh([_PROJECT])

    assert deleter.fleet_exists.call_count == 2
    job.refresh_from_db()
    assert job.fleet_deleted_at is not None
    assert job.job_events.get(event_type="FLEET_DELETED").data == {"fleet_id": "fleet-0", "reason": "retention"}
    assert cache.deleting() == set()


def test_a_list_refreshes_the_deleting_fleets_so_no_get_is_needed(program):
    job = _job(program, "fleet-0")
    cache, deleter, clock = _cache({"fleet-0": "deleting"})
    cache.refresh([_PROJECT])
    cache.record_delete(_PROJECT, str(job.id), "fleet-0", "retention")

    clock.now += LIST_EVERY_SECONDS
    cache.refresh([_PROJECT])

    deleter.fleet_exists.assert_not_called()
    assert cache.deleting() == {"fleet-0"}


def test_a_list_that_started_before_our_delete_does_not_bring_the_fleet_back(program):
    job = _job(program, "fleet-0")
    cache, deleter, clock = _cache({"fleet-0": "standby"})
    cache.refresh([_PROJECT])

    def list_then_delete(handler, region, deadline):
        clock.now += 1
        cache.record_delete(_PROJECT, str(job.id), "fleet-0", "retention")
        return {"fleet-0": "standby"}

    deleter.list_fleets.side_effect = list_then_delete
    clock.now += LIST_EVERY_SECONDS
    cache.refresh([_PROJECT])

    assert cache.deleting() == {"fleet-0"}


def test_a_failed_list_runs_again_on_the_next_cycle_and_a_refused_one_waits(program):
    _job(program, "fleet-0")
    cache, deleter, clock = _cache(list_error=RunnerRetryableError("503"))
    cache.refresh([_PROJECT])
    clock.now += 1
    cache.refresh([_PROJECT])
    assert deleter.list_fleets.call_count == 2

    deleter.list_fleets.side_effect = RunnerError("403")
    clock.now += 1
    cache.refresh([_PROJECT])
    clock.now += 1
    cache.refresh([_PROJECT])
    assert deleter.list_fleets.call_count == 3


def test_a_stuck_delete_is_reported_once(program, caplog):
    job = _job(program, "fleet-0")
    cache, _, clock = _cache({"fleet-0": "standby"})
    cache.refresh([_PROJECT])
    cache.record_delete(_PROJECT, str(job.id), "fleet-0", "retention")

    clock.now += STUCK_AFTER_SECONDS
    cache.refresh([_PROJECT])
    clock.now += CHECK_EVERY_SECONDS
    cache.refresh([_PROJECT])

    assert caplog.text.count("still deleting") == 1


def test_a_paused_region_gets_no_list_and_no_get(program):
    _job(program, "fleet-0")
    cache, deleter, _ = _cache({})
    deleter.paused.return_value = True

    cache.refresh([_PROJECT])

    deleter.list_fleets.assert_not_called()
    deleter.fleet_exists.assert_not_called()


def test_a_row_without_a_project_is_never_checked(program):
    TestUtils.create_job(
        author=program.author, program=program, status=Job.SUCCEEDED, runner=Program.FLEETS, fleet_id="legacy"
    )
    _job(program, "fleet-0")
    cache, deleter, _ = _cache({})

    cache.refresh([_PROJECT])

    assert [call.args[2] for call in deleter.fleet_exists.call_args_list] == ["fleet-0"]


def test_a_fleet_is_stamped_once_whoever_finds_it_gone(program):
    job = _job(program, "fleet-0")

    first = Job.objects.stamp_fleet_deleted(job.id, "fleet-0", "retention")
    second = Job.objects.stamp_fleet_deleted(job.id, "fleet-0", "found_deleted")

    assert (first, second) == (True, False)
    assert job.job_events.filter(event_type="FLEET_DELETED").count() == 1


def test_a_fleet_never_has_two_gets_in_flight(program):
    job = _job(program, "fleet-0")
    queued = []
    cache, deleter, clock = _cache({"fleet-0": "standby"})
    cache.refresh([_PROJECT])
    cache.record_delete(_PROJECT, str(job.id), "fleet-0", "retention")
    cache._submit = (
        lambda fn, *args, replace_key=None: queued.append(replace_key) or Future()
    )  # pylint: disable=protected-access

    clock.now += CHECK_EVERY_SECONDS
    cache.refresh([_PROJECT])
    clock.now += CHECK_EVERY_SECONDS
    cache.refresh([_PROJECT])

    assert queued == ["fleet-0"]
    deleter.fleet_exists.assert_not_called()


def test_a_quiet_project_costs_no_query(program, django_assert_num_queries):
    _job(program, "fleet-0")
    cache, _, _ = _cache({"fleet-0": "standby"})
    cache.refresh([_PROJECT])

    with django_assert_num_queries(0):
        assert cache.need(_PROJECT, _THRESHOLD, held=1) == 0


def test_a_held_fleet_the_list_misses_is_new_unless_it_ended_before_the_list(program):
    _job(program, "listed")
    _job(program, "running", status=Job.RUNNING)
    _job(program, "ended-before", age_hours=2)
    _job(program, "ended-after", age_hours=0)

    new, stale = Job.objects.missing_from_list(_PROJECT, ["listed"], timezone.now() - timedelta(hours=1))

    assert set(new.values_list("fleet_id", flat=True)) == {"running", "ended-after"}
    assert set(stale.values_list("fleet_id", flat=True)) == {"ended-before"}
