"""Tests for the migrate_job_business_model command."""

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import QuerySet

from core.domain.business_models import BusinessModel
from core.models import Job

pytestmark = pytest.mark.django_db


def _stored_business_model(job: Job) -> str:
    """Read the raw column, since Job.from_db translates the old name away."""
    return Job.objects.filter(pk=job.id).values_list("business_model", flat=True).first()


@pytest.fixture()
def jobs():
    """Three jobs holding the old name and one holding TRIAL."""
    author = User.objects.create_user(username="job-author")
    old = [Job.objects.create(author=author, business_model=BusinessModel.SUBSIDIZED) for _ in range(3)]
    trial = Job.objects.create(author=author, business_model=BusinessModel.TRIAL)
    return old, trial


def test_all_old_jobs_are_updated_in_batches(jobs):
    """Every SUBSIDIZED row becomes LICENSED, even when it takes more than one batch."""
    old, trial = jobs

    call_command("migrate_job_business_model", batch_size=2, sleep=0)

    for job in old:
        assert _stored_business_model(job) == BusinessModel.LICENSED
    assert _stored_business_model(trial) == BusinessModel.TRIAL


def test_bumps_version_so_a_concurrent_save_detects_the_change(jobs):
    """version is a django-concurrency field: a stale save() must still be able to detect this write."""
    old, _ = jobs

    versions_before = [job.version for job in old]
    call_command("migrate_job_business_model", batch_size=2, sleep=0)

    for job, version_before in zip(old, versions_before):
        job.refresh_from_db(fields=["version"])
        assert job.version == version_before + 1


def test_dry_run_writes_nothing(jobs):
    old, _ = jobs

    call_command("migrate_job_business_model", dry_run=True, sleep=0)

    for job in old:
        assert _stored_business_model(job) == BusinessModel.SUBSIDIZED


@pytest.mark.parametrize("batch_size", [0, -1])
def test_rejects_non_positive_batch_size(jobs, batch_size):
    old, _ = jobs

    with pytest.raises(CommandError, match="--batch-size"):
        call_command("migrate_job_business_model", batch_size=batch_size, sleep=0)

    for job in old:
        assert _stored_business_model(job) == BusinessModel.SUBSIDIZED


def test_rejects_negative_sleep(jobs):
    old, _ = jobs

    with pytest.raises(CommandError, match="--sleep"):
        call_command("migrate_job_business_model", sleep=-1)

    for job in old:
        assert _stored_business_model(job) == BusinessModel.SUBSIDIZED


def test_raises_when_jobs_are_still_pending_after_the_loop(jobs, monkeypatch):
    """A row that reappears between the last batch and the completion check must fail loud."""
    old, trial = jobs
    original_count = QuerySet.count
    calls = {"n": 0}

    def fake_count(self):
        calls["n"] += 1
        if calls["n"] == 2:
            Job.objects.create(author=trial.author, business_model=BusinessModel.SUBSIDIZED)
        return original_count(self)

    monkeypatch.setattr(QuerySet, "count", fake_count)

    with pytest.raises(CommandError, match="still hold"):
        call_command("migrate_job_business_model", batch_size=len(old), sleep=0)
