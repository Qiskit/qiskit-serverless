"""Tests for Job model fields."""

import pytest
from django.contrib.auth.models import User
from django.db import models

from core.models import Job

pytestmark = pytest.mark.django_db


def test_filler_defaults_to_false_and_is_queryable():
    """A job created without filler is a real job, and the column can be filtered on."""
    author = User.objects.create_user(username="filler-test-author")
    job = Job.objects.create(author=author)

    assert job.filler is False
    assert Job.objects.filter(filler=False).count() == 1

    job.filler = True
    job.save()

    assert Job.objects.filter(filler=True).count() == 1


def test_filler_partial_index_is_declared():
    """A partial index on created covers the filler lookup the scheduler runs every second."""
    index = next((i for i in Job._meta.indexes if i.name == "job_filler_true_idx"), None)

    assert index is not None
    assert index.fields == ["created"]
    assert index.condition == models.Q(filler=True)


def test_update_fields_moves_the_updated_timestamp():
    """A status change through update_fields is a change, so updated must move."""
    author = User.objects.create_user(username="updated-test-author-1")
    job = Job.objects.create(author=author, status=Job.QUEUED)
    before = job.updated

    job.update_fields({"status": Job.RUNNING})

    assert job.updated > before
    assert Job.objects.get(pk=job.pk).updated == job.updated


def test_save_direct_moves_the_updated_timestamp():
    """save_direct bypasses save(), so it has to stamp updated itself."""
    author = User.objects.create_user(username="updated-test-author-2")
    job = Job.objects.create(author=author, status=Job.QUEUED)
    before = job.updated

    job.status = Job.RUNNING
    job.save_direct(["status"])

    assert job.updated > before
    assert Job.objects.get(pk=job.pk).updated == job.updated
