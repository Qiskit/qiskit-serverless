"""Unit tests for the generic Outbox model: no business predicates live here anymore, just
confirming the schema behaves (create, filter by channel ordered by created, delete)."""

import pytest
from django.contrib.auth.models import User

from core.models import Job, Outbox, Program

pytestmark = pytest.mark.django_db


@pytest.fixture
def job():
    user = User.objects.create_user(username="author")
    return Job.objects.create(author=user, runner=Program.FLEETS)


class TestOutboxModel:
    def test_create_and_read_back(self, job):
        row = Outbox.objects.create(job=job, channel="billing", payload={"a": 1})

        fetched = Outbox.objects.get(pk=row.pk)
        assert fetched.job_id == job.id
        assert fetched.channel == "billing"
        assert fetched.payload == {"a": 1}
        assert fetched.created is not None

    def test_filter_by_channel_orders_by_created(self, job):
        older = Outbox.objects.create(job=job, channel="billing", payload={})
        Outbox.objects.filter(pk=older.pk).update(created="2020-01-01T00:00:00Z")
        newer = Outbox.objects.create(job=job, channel="billing", payload={})
        other_channel = Outbox.objects.create(job=job, channel="workload", payload={})

        rows = list(Outbox.objects.filter(channel="billing").order_by("created"))

        assert rows == [older, newer]
        assert other_channel not in rows

    def test_delete_removes_the_row(self, job):
        row = Outbox.objects.create(job=job, channel="billing", payload={})

        row.delete()

        assert not Outbox.objects.filter(pk=row.pk).exists()
