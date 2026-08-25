"""Tests for the temporary business model translation done when a job row is read."""

import pytest
from django.contrib.auth.models import User

from core.domain.business_models import BusinessModel
from core.models import Job

pytestmark = pytest.mark.django_db


@pytest.fixture()
def old_job():
    """A job row still holding the old SUBSIDIZED business model name."""
    author = User.objects.create_user(username="job-author")
    job = Job.objects.create(author=author, status=Job.QUEUED)
    Job.objects.filter(pk=job.id).update(business_model=BusinessModel.SUBSIDIZED)
    return job


def test_old_job_is_read_as_licensed(old_job):
    assert Job.objects.get(pk=old_job.id).business_model == BusinessModel.LICENSED


def test_deferred_query_does_not_load_the_business_model(old_job):
    """only() leaves the field out, so the translation must not touch it."""
    job = Job.objects.only("id", "status").get(pk=old_job.id)

    assert "business_model" not in job.__dict__
