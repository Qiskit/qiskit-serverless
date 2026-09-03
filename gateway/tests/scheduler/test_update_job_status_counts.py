"""Unit tests for UpdateJobStatusCounts."""

from unittest.mock import MagicMock, patch, call

import pytest
from prometheus_client import CollectorRegistry

from core.models import Job
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.tasks.update_job_status_counts import UpdateJobStatusCounts
from tests.utils import TestUtils

_MOD = "scheduler.tasks.update_job_status_counts"


def _make_task():
    kill_signal = MagicMock()
    kill_signal.received = False
    return UpdateJobStatusCounts(kill_signal=kill_signal, metrics=MagicMock())


def test_job_status_counts_clears_and_sets_metrics():
    """run() clears existing counts then sets one entry per (status, provider) pair."""
    task = _make_task()

    fake_rows = [
        {"status": "QUEUED", "program__provider__name": "ibm", "count": 3},
        {"status": "RUNNING", "program__provider__name": None, "count": 1},
    ]

    with patch(f"{_MOD}.Job") as MockJob:
        MockJob.QUEUED = "QUEUED"
        MockJob.PENDING = "PENDING"
        MockJob.RUNNING = "RUNNING"
        MockJob.objects.filter.return_value.exclude.return_value.values.return_value.annotate.return_value = fake_rows
        task.run()

    task.metrics.clear_job_status_counts.assert_called_once()
    task.metrics.set_job_status_count.assert_any_call(3, "QUEUED", "ibm")
    task.metrics.set_job_status_count.assert_any_call(1, "RUNNING", "custom")


def test_job_status_counts_exclude_filler_jobs():
    """Filler jobs are excluded from the per-provider counts and reported on their own gauge."""
    task = _make_task()

    real_rows = [{"status": "RUNNING", "program__provider__name": "ibm", "count": 2}]
    filler_rows = [{"status": "RUNNING", "count": 4}]

    with patch(f"{_MOD}.Job") as MockJob:
        MockJob.QUEUED = "QUEUED"
        MockJob.PENDING = "PENDING"
        MockJob.RUNNING = "RUNNING"
        real_query = MockJob.objects.filter.return_value.exclude.return_value
        real_query.values.return_value.annotate.return_value = real_rows
        filler_query = MockJob.objects.filter.return_value.filter.return_value
        filler_query.values.return_value.annotate.return_value = filler_rows
        task.run()

    MockJob.objects.filter.return_value.exclude.assert_called_once_with(filler=True)
    task.metrics.set_job_status_count.assert_called_once_with(2, "RUNNING", "ibm")
    task.metrics.clear_filler_jobs_counts.assert_called_once()
    task.metrics.set_filler_jobs_count.assert_called_once_with(4, "RUNNING")


@pytest.mark.django_db
def test_the_gauges_split_real_and_filler_jobs_against_a_real_database():
    """The SQL, not just the call, has to separate them, and stale series must go."""
    metrics = SchedulerMetrics(CollectorRegistry())
    task = UpdateJobStatusCounts(kill_signal=MagicMock(received=False), metrics=metrics)
    program = TestUtils.create_program(program_title="counts-function", author="counts_user")
    TestUtils.create_job(author="counts_user", program=program, status=Job.RUNNING)
    filler = TestUtils.create_job(author="counts_user", program=program, status=Job.RUNNING, filler=True)

    task.run()

    assert metrics.job_status_count.labels(status=Job.RUNNING, provider="custom")._value.get() == 1
    assert metrics.filler_jobs_count.labels(status=Job.RUNNING)._value.get() == 1

    filler.delete()
    task.run()

    assert metrics.filler_jobs_count._metrics == {}
