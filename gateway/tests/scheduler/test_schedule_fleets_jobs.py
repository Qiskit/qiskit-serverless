"""Unit tests for ScheduleFleetsJobs."""

import math
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from core.config_key import ConfigKey
from core.models import Config, Job
from core.services.runners import RunnerError
from core.services.runners import RunnerRetryableError
from scheduler.tasks.schedule_fleets_jobs import ScheduleFleetsJobs

_MOD = "scheduler.tasks.schedule_fleets_jobs"


@pytest.fixture(autouse=True)
def fleet_count():
    with patch(f"{_MOD}.count_fleets", side_effect=RunnerError("not counted in unit tests")) as count:
        yield count


def _make_task():
    kill_signal = MagicMock()
    kill_signal.received = False
    return ScheduleFleetsJobs(kill_signal=kill_signal, metrics=MagicMock())


def _job(project_name="ce-test"):
    job = MagicMock(env_vars="{}", ce_region="us-east")
    job.program.code_engine_project.id = hash(project_name)
    job.program.code_engine_project.project_name = project_name
    job.program.code_engine_project.active = True
    return job


def _schedule(jobs, free_fleets, submits=None):
    task = _make_task()
    with (
        patch(f"{_MOD}.get_jobs_to_schedule_fair_share", return_value=jobs),
        patch.object(ScheduleFleetsJobs, "_free_fleets", side_effect=free_fleets) as mock_free_fleets,
        patch.object(task.submitter, "submit", return_value=True, side_effect=submits) as mock_submit,
    ):
        task._schedule_jobs_if_slots_available(max_slots_possible=5, number_of_slots_running=0)
    return [call.args[0] for call in mock_submit.call_args_list], mock_free_fleets


def test_fleets_execute_called_with_ctx():
    """submit is called with the job and the tracing context extracted from env_vars."""
    task = _make_task()

    mock_job = MagicMock()
    mock_job.fleet_id = "fleet-abc"
    mock_job.status = "PENDING"
    mock_job.gpu = False
    mock_job.env_vars = '{"traceparent": null}'
    mock_job.created = datetime(2026, 1, 1, tzinfo=timezone.utc)

    mock_ctx = MagicMock()

    with (
        patch(f"{_MOD}.get_jobs_to_schedule_fair_share", return_value=[mock_job]),
        patch.object(task.submitter, "submit", return_value=True) as mock_execute,
        patch(f"{_MOD}.TraceContextTextMapPropagator") as mock_propagator,
    ):
        mock_propagator.return_value.extract.return_value = mock_ctx
        task._schedule_jobs_if_slots_available(max_slots_possible=5, number_of_slots_running=0)

    mock_execute.assert_called_once_with(mock_job, mock_ctx)


def test_a_submit_that_did_not_reach_pending_records_no_queue_wait():
    """The queue-wait sample is only meaningful for a job that actually started. submit() raises
    rather than returning, so reaching the metric at all means the job is PENDING."""
    task = _make_task()
    mock_job = MagicMock(status=Job.QUEUED, gpu=False, env_vars='{"traceparent": null}', filler=False)
    mock_job.created = datetime(2026, 1, 1, tzinfo=timezone.utc)

    with (
        patch(f"{_MOD}.get_jobs_to_schedule_fair_share", return_value=[mock_job]),
        patch.object(task.submitter, "submit", side_effect=RunnerError("Code Engine refused")),
        patch(f"{_MOD}.TraceContextTextMapPropagator"),
    ):
        task._schedule_jobs_if_slots_available(max_slots_possible=5, number_of_slots_running=0)

    task.metrics.observe_queue_wait_time.assert_not_called()


def test_add_queue_wait_time_metric_skips_filler_jobs():
    """Filler jobs skip the queue by design; the wait-time metric is only for real jobs."""
    task = _make_task()

    filler_job = MagicMock(spec=Job)
    filler_job.filler = True
    filler_job.created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    filler_job.gpu = False

    task.add_queue_wait_time_metric(filler_job)
    task.metrics.observe_queue_wait_time.assert_not_called()

    real_job = MagicMock(spec=Job)
    real_job.filler = False
    real_job.created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    real_job.gpu = False

    task.add_queue_wait_time_metric(real_job)
    task.metrics.observe_queue_wait_time.assert_called_once()


def test_a_code_engine_failure_skips_only_that_region_for_the_tick():
    task = _make_task()
    failing = MagicMock(env_vars="{}", ce_region="us-east")
    same_region = MagicMock(env_vars="{}", ce_region="us-east")
    other_region = MagicMock(env_vars="{}", ce_region="eu-de")

    def submit(job, ctx):  # pylint: disable=unused-argument
        if job is failing:
            raise RunnerRetryableError("Too Many Requests")
        return job

    with (
        patch(f"{_MOD}.get_jobs_to_schedule_fair_share", return_value=[failing, same_region, other_region]),
        patch.object(task.submitter, "submit", side_effect=submit) as mock_submit,
    ):
        task._schedule_jobs_if_slots_available(max_slots_possible=5, number_of_slots_running=0)

    assert [call.args[0] for call in mock_submit.call_args_list] == [failing, other_region]
    # the breaker is still closed after a 429, so the job left behind is not one a breaker held back
    task.metrics.increment_fleets_jobs_skipped_by_breaker.assert_not_called()


def test_a_job_in_a_paused_region_is_not_submitted():
    task = _make_task()
    paused = MagicMock(env_vars="{}", ce_region="us-east")
    same_region = MagicMock(env_vars="{}", ce_region="us-east")
    other = MagicMock(env_vars="{}", ce_region="eu-de")

    with (
        patch(f"{_MOD}.get_jobs_to_schedule_fair_share", return_value=[paused, same_region, other]),
        patch.object(task.submitter, "paused", side_effect=lambda region: region == "us-east"),
        patch.object(task.submitter, "submit", side_effect=lambda job, ctx: True) as mock_submit,
    ):
        task._schedule_jobs_if_slots_available(max_slots_possible=5, number_of_slots_running=0)

    assert [call.args[0] for call in mock_submit.call_args_list] == [other]
    # both jobs of the paused region are counted, the one that found the breaker open and the one skipped after it
    assert task.metrics.increment_fleets_jobs_skipped_by_breaker.call_count == 2


def test_a_failed_submit_keeps_its_free_fleet():
    jobs = [_job(), _job()]

    submitted, _ = _schedule(jobs, lambda project: 1, submits=[RunnerError("refused"), True])

    assert submitted == jobs


def test_a_project_with_no_free_fleet_keeps_its_jobs_queued():
    full, other = _job("full"), _job("other")

    submitted, _ = _schedule([full, other], lambda project: 0 if project.project_name == "full" else math.inf)

    assert submitted == [other]


def test_each_submit_takes_one_free_fleet_of_its_project():
    jobs = [_job(), _job(), _job()]

    submitted, free_fleets = _schedule(jobs, lambda project: 2)

    assert submitted == jobs[:2]
    free_fleets.assert_called_once()


def test_a_job_without_an_active_project_is_not_counted():
    no_project = MagicMock(env_vars="{}", ce_region="us-east", program=None)
    inactive = _job()
    inactive.program.code_engine_project.active = False

    submitted, free_fleets = _schedule([no_project, inactive], lambda project: 0)

    assert submitted == [no_project, inactive]
    free_fleets.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize("count, expected", [(8, 2), (12, 0)])
def test_free_fleets_is_the_quota_less_the_fleets_code_engine_counts(fleet_count, count, expected):
    Config.add_defaults()
    Config.set(ConfigKey.FLEETS_QUOTA_PER_PROJECT, "10")
    fleet_count.side_effect = None
    fleet_count.return_value = count

    assert ScheduleFleetsJobs._free_fleets(MagicMock()) == expected


def test_free_fleets_is_unlimited_when_code_engine_cannot_count(fleet_count):
    fleet_count.side_effect = RunnerRetryableError("Too Many Requests")

    assert ScheduleFleetsJobs._free_fleets(MagicMock()) == math.inf
