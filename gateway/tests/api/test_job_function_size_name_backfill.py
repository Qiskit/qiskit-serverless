"""Tests for the 0078 backfill of Job.function_size_name from the job's current size row."""

import importlib

import pytest
from django.apps import apps
from django.contrib.auth.models import User

from core.models import ComputeProfile, FunctionSize, Job, Program

backfill_function_size_name = importlib.import_module(
    "api.migrations.0078_job_function_size_name"
).backfill_function_size_name


@pytest.mark.django_db
def test_backfill_copies_the_current_size_label_and_leaves_jobs_without_a_row_null():
    """Migration 0078 backfill, happy path: a job with a size row gets that row's label copied into
    function_size_name, and a job with no size row (Ray, or a row already deleted) is left null."""
    author = User.objects.create_user(username="alice")
    program = Program.objects.create(title="my-fn", author=author, runner=Program.FLEETS)
    profile = ComputeProfile.objects.create(compute_profile_id="16x128", cpu="16", memory="128")
    size = FunctionSize.objects.create(function=program, function_size="M", compute_profile=profile)
    sized = Job.objects.create(author=author, program=program, runner=Program.FLEETS, function_size=size)
    unsized = Job.objects.create(author=author, program=program, runner=Program.RAY)

    backfill_function_size_name(apps, None)

    assert Job.objects.get(pk=sized.pk).function_size_name == size.function_size
    assert Job.objects.get(pk=unsized.pk).function_size_name is None


@pytest.mark.django_db
def test_backfill_uppercases_a_legacy_lowercase_size_row():
    """Migration 0078 backfill, legacy data: a size row still stored lowercase ("m") is copied as "M". The backfill
    reads the raw column, which skips FunctionSize.from_db(), so without Upper() the job would be billed under a
    different key than a job created after the upgrade."""
    author = User.objects.create_user(username="alice")
    program = Program.objects.create(title="my-fn", author=author, runner=Program.FLEETS)
    profile = ComputeProfile.objects.create(compute_profile_id="16x128", cpu="16", memory="128")
    size = FunctionSize.objects.create(function=program, function_size="M", compute_profile=profile)
    FunctionSize.objects.filter(pk=size.pk).update(function_size="m")
    job = Job.objects.create(author=author, program=program, runner=Program.FLEETS, function_size=size)

    backfill_function_size_name(apps, None)

    assert Job.objects.get(pk=job.pk).function_size_name == "M"
