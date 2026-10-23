from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from prometheus_client import CollectorRegistry

from core import job_status_metrics
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from core.models import Job, JobEvent, Program
from core.services.job_transitions import JobTransitionService

pytestmark = pytest.mark.django_db


@pytest.fixture(name="registry")
def registry_fixture():
    registry = CollectorRegistry()
    job_status_metrics.enable(registry)
    yield registry
    job_status_metrics.disable()


def _sample(registry, suffix, status, final_status, compute_type="cpu"):
    return registry.get_sample_value(
        f"scheduler_job_status_duration_seconds_{suffix}",
        {"status": status, "final_status": final_status, "compute_type": compute_type},
    )


def _queued_job(filler=False, entered_seconds_ago=0, gpu=False):
    author = User.objects.create_user(username=f"metric-author-{filler}-{entered_seconds_ago}-{gpu}")
    job = Job.objects.create(author=author, runner=Program.FLEETS, status=Job.QUEUED, filler=filler, gpu=gpu)
    event = JobEvent.objects.add_status_event(
        job_id=job.id, origin=JobEventOrigin.API, context=JobEventContext.RUN_PROGRAM, status=Job.QUEUED
    )
    JobEvent.objects.filter(pk=event.pk).update(
        created=datetime.now(timezone.utc) - timedelta(seconds=entered_seconds_ago)
    )
    return job


def _schedule(job):
    JobTransitionService(sender=MagicMock()).queued_to_pending(
        job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.SCHEDULE_JOBS
    )


def test_leaving_a_status_records_how_long_the_job_was_in_it(registry):
    job = _queued_job(entered_seconds_ago=40)

    _schedule(job)

    assert _sample(registry, "count", Job.QUEUED, Job.PENDING) == 1
    assert 40 <= _sample(registry, "sum", Job.QUEUED, Job.PENDING) < 60


def test_a_gpu_job_is_recorded_as_gpu(registry):
    job = _queued_job(gpu=True)

    _schedule(job)

    assert _sample(registry, "count", Job.QUEUED, Job.PENDING, compute_type="gpu") == 1


def test_filler_jobs_are_left_out(registry):
    job = _queued_job(filler=True)

    _schedule(job)

    assert _sample(registry, "count", Job.QUEUED, Job.PENDING) is None


def test_the_gateway_does_not_query_for_a_duration_it_would_throw_away():
    job = _queued_job()

    with patch.object(JobEvent.objects, "first_status_at") as first_status_at:
        JobTransitionService(sender=MagicMock()).queued_to_pending(
            job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.SCHEDULE_JOBS
        )

    first_status_at.assert_not_called()
