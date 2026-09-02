"""Tests for Job model fields."""

import pytest
from django.contrib.auth.models import User

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
