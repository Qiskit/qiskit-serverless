"""Unit tests for StopBlockedFleetsJobs."""

from unittest.mock import MagicMock

import pytest

from core.config_key import ConfigKey
from core.domain.exceptions.invalid_job_transition_exception import InvalidJobTransitionException
from core.model_managers.job_events import JobEventContext, JobEventType
from core.models import BlockedCloudResource, Config, Job, JobEvent, Program
from core.services.runners import RunnerError, RunnerRetryableError
from scheduler.tasks.stop_blocked_fleets_jobs import BLOCKED_RESOURCE_ERROR_CODE, StopBlockedFleetsJobs
from tests.utils import TestUtils

pytestmark = pytest.mark.django_db

_BLOCKED = {"account_id": "acct", "plan_id": "plan", "subscription_id": "sub"}


@pytest.fixture(autouse=True)
def blocked_resource():
    Config.add_defaults()
    BlockedCloudResource.objects.create(account="acct", plan="plan", subscription="sub")


def _make_task():
    kill_signal = MagicMock()
    kill_signal.received = False
    canceller = MagicMock()
    canceller.paused.return_value = False
    canceller.cancel.return_value = True
    return StopBlockedFleetsJobs(kill_signal, canceller)


def _error_events(job):
    return list(JobEvent.objects.filter(job=job, event_type=JobEventType.ERROR))


def _make_job(status=Job.RUNNING, **fields):
    defaults = {"runner": Program.FLEETS, "fleet_id": "fleet-123", "ce_region": "us-east", **_BLOCKED}
    return TestUtils.create_job(author="user", program="function", status=status, **{**defaults, **fields})


@pytest.mark.parametrize("status", [Job.PENDING, Job.RUNNING])
def test_a_blocked_job_in_code_engine_is_cancelled(status):
    task = _make_task()
    job = _make_job(status)

    task.run()

    task.canceller.cancel.assert_called_once_with(job, context=JobEventContext.BLOCKED_RESOURCE_STOP)


@pytest.mark.parametrize(
    "fields",
    [
        {"status": Job.QUEUED},
        {"status": Job.STOPPING},
        {"status": Job.SUCCEEDED},
        {"filler": True},
        {"runner": Program.RAY},
        {"plan_id": "other-plan"},
        {"subscription_id": None},
    ],
)
def test_jobs_this_task_does_not_cancel(fields):
    task = _make_task()
    _make_job(**fields)

    task.run()

    task.canceller.cancel.assert_not_called()


def test_the_kill_switch_turns_the_task_off():
    Config.set(ConfigKey.BLOCKED_JOBS_STOP_ENABLED, "false")
    task = _make_task()
    _make_job()

    task.run()

    task.canceller.cancel.assert_not_called()


def test_a_paused_region_sends_no_cancel():
    task = _make_task()
    task.canceller.paused.return_value = True
    _make_job()

    task.run()

    task.canceller.cancel.assert_not_called()


def test_nothing_to_cancel_ends_the_job_as_stopped():
    task = _make_task()
    task.canceller.cancel.return_value = False
    job = _make_job()

    task.run()

    task.canceller.transitions.to_stopped.assert_called_once()
    assert task.canceller.transitions.to_stopped.call_args.args == (job,)


@pytest.mark.parametrize(
    "error", [RunnerRetryableError("429"), RunnerError("no project"), InvalidJobTransitionException("lost race")]
)
def test_a_cancel_that_does_not_land_writes_nothing_and_the_next_job_is_still_tried(error):
    task = _make_task()
    task.canceller.cancel.side_effect = [error, True]
    _make_job()
    _make_job()

    task.run()

    assert task.canceller.cancel.call_count == 2
    task.canceller.transitions.to_stopped.assert_not_called()


def test_the_error_code_is_the_one_the_client_reads():
    assert BLOCKED_RESOURCE_ERROR_CODE == "BLOCKED_RESOURCE"


@pytest.mark.parametrize("cancelled", [True, False])
def test_a_stopped_job_gets_an_error_event_naming_the_block(cancelled):
    task = _make_task()
    task.canceller.cancel.return_value = cancelled
    job = _make_job()

    task.run()

    [event] = _error_events(job)
    assert event.context == JobEventContext.BLOCKED_RESOURCE_STOP
    assert event.data["code"] == BLOCKED_RESOURCE_ERROR_CODE
    assert "blocked" in event.data["message"]
    assert event.data["args"] == {"account_id": "acct", "plan_id": "plan", "subscription_id": "sub"}


@pytest.mark.parametrize(
    "error", [RunnerRetryableError("429"), RunnerError("no project"), InvalidJobTransitionException("lost race")]
)
def test_a_cancel_that_does_not_land_writes_no_error_event(error):
    task = _make_task()
    task.canceller.cancel.side_effect = error
    job = _make_job()

    task.run()

    assert not _error_events(job)
