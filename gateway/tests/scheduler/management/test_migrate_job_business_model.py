"""Tests for the migrate_job_business_model command."""

import logging
from typing import NamedTuple

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


class _Jobs(NamedTuple):
    old: list[Job]
    trial: Job
    consumption: Job
    licensed: Job


@pytest.fixture()
def jobs() -> _Jobs:
    """Three jobs holding the old name, plus one of every other business model."""
    author = User.objects.create_user(username="job-author")
    old = [Job.objects.create(author=author, business_model=BusinessModel.SUBSIDIZED) for _ in range(3)]
    trial = Job.objects.create(author=author, business_model=BusinessModel.TRIAL)
    consumption = Job.objects.create(author=author, business_model=BusinessModel.CONSUMPTION)
    licensed = Job.objects.create(author=author, business_model=BusinessModel.LICENSED)
    return _Jobs(old, trial, consumption, licensed)


def test_all_old_jobs_are_updated_in_batches(jobs):
    """Every SUBSIDIZED row becomes LICENSED; every other business model is left alone."""
    call_command("migrate_job_business_model", batch_size=2, sleep=0)

    for job in jobs.old:
        assert _stored_business_model(job) == BusinessModel.LICENSED
    assert _stored_business_model(jobs.trial) == BusinessModel.TRIAL
    assert _stored_business_model(jobs.consumption) == BusinessModel.CONSUMPTION
    assert _stored_business_model(jobs.licensed) == BusinessModel.LICENSED


def test_bumps_version_so_a_concurrent_save_detects_the_change(jobs):
    """version is a django-concurrency field: a stale save() must still be able to detect this write."""
    versions_before = [job.version for job in jobs.old]
    call_command("migrate_job_business_model", batch_size=2, sleep=0)

    for job, version_before in zip(jobs.old, versions_before):
        job.refresh_from_db(fields=["version"])
        assert job.version == version_before + 1


def test_updated_count_reflects_affected_rows_not_selected_ids(jobs, monkeypatch, caplog):
    """A row deleted between the SELECT and the UPDATE must not inflate the reported count."""
    original_update = QuerySet.update
    deleted = {"done": False}

    def fake_update(self, **kwargs):
        if not deleted["done"]:
            deleted["done"] = True
            jobs.old[0].delete()
        return original_update(self, **kwargs)

    monkeypatch.setattr(QuerySet, "update", fake_update)

    with caplog.at_level(logging.INFO, logger="commands"):
        call_command("migrate_job_business_model", batch_size=len(jobs.old), sleep=0)

    assert "Finished, 2 jobs updated" in caplog.text


def test_dry_run_writes_nothing(jobs):
    call_command("migrate_job_business_model", dry_run=True, sleep=0)

    for job in jobs.old:
        assert _stored_business_model(job) == BusinessModel.SUBSIDIZED


@pytest.mark.parametrize("batch_size", [0, -1])
def test_rejects_non_positive_batch_size(jobs, batch_size):
    with pytest.raises(CommandError, match="--batch-size"):
        call_command("migrate_job_business_model", batch_size=batch_size, sleep=0)

    for job in jobs.old:
        assert _stored_business_model(job) == BusinessModel.SUBSIDIZED


def test_rejects_negative_sleep(jobs):
    with pytest.raises(CommandError, match="--sleep"):
        call_command("migrate_job_business_model", sleep=-1)

    for job in jobs.old:
        assert _stored_business_model(job) == BusinessModel.SUBSIDIZED


def test_raises_when_jobs_are_still_pending_after_the_loop(jobs, monkeypatch):
    """A row that reappears between the last batch and the completion check must fail loud."""
    original_count = QuerySet.count
    calls = {"n": 0}

    def fake_count(self):
        calls["n"] += 1
        if calls["n"] == 2:
            Job.objects.create(author=jobs.trial.author, business_model=BusinessModel.SUBSIDIZED)
        return original_count(self)

    monkeypatch.setattr(QuerySet, "count", fake_count)

    with pytest.raises(CommandError, match="still hold"):
        call_command("migrate_job_business_model", batch_size=len(jobs.old), sleep=0)
