"""Tests for Job model fields."""

import pytest
from django.contrib.auth.models import User
from django.db import models

from core.model_managers.job_events import JobEventContext, JobEventOrigin
from core.models import ComputeProfile, FunctionSize, Job, JobEvent, Outbox, Program, Provider

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return User.objects.create_user(username="author")


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


class TestChangeStatus:
    """Unit tests for Job.change_status()."""

    def test_persists_status_and_job_fields(self):
        author = User.objects.create_user(username="change-status-author-1")
        job = Job.objects.create(author=author, status=Job.QUEUED)

        job.change_status(
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.UPDATE_JOB_STATUS,
            status=Job.RUNNING,
            job_fields={"sub_status": "mapping"},
        )

        job.refresh_from_db()
        assert job.status == Job.RUNNING
        assert job.sub_status == "mapping"

    def test_creates_the_status_change_event(self):
        author = User.objects.create_user(username="change-status-author-2")
        job = Job.objects.create(author=author, status=Job.RUNNING)

        event = job.change_status(
            origin=JobEventOrigin.API,
            context=JobEventContext.STOP_JOB,
            status=Job.STOPPED,
        )

        assert event.data == {"status": Job.STOPPED}
        assert event.origin == JobEventOrigin.API
        assert event.context == JobEventContext.STOP_JOB

    def test_rolls_back_the_event_if_the_job_write_fails(self, monkeypatch):
        """Event-then-job must be all-or-nothing: a failed job write must not leave
        a JobEvent behind with no matching state change."""
        author = User.objects.create_user(username="change-status-author-3")
        job = Job.objects.create(author=author, status=Job.QUEUED)

        def _boom(self, fields_map):  # pylint: disable=unused-argument
            raise RuntimeError("boom")

        monkeypatch.setattr(Job, "update_fields", _boom)

        with pytest.raises(RuntimeError, match="boom"):
            job.change_status(
                origin=JobEventOrigin.SCHEDULER,
                context=JobEventContext.UPDATE_JOB_STATUS,
                status=Job.RUNNING,
            )

        assert JobEvent.objects.filter(job=job).count() == 0


class TestChangeStatusEnqueuesOutboxMessages:
    """Job.change_status is the only place that builds and stores outbox messages, and only for
    an eligible job (Fleets, not filler, with an instance CRN) transitioning to a terminal
    status."""

    def test_succeeded_enqueues_both_messages_even_without_a_running_event(self, user):
        """The short-job-between-two-polls case: never observed RUNNING, still owes the fee."""
        provider = Provider.objects.create(name="ibm-dev")
        program = Program.objects.create(
            title="my-fn", author=user, entrypoint="main.py", runner=Program.FLEETS, provider=provider
        )
        profile = ComputeProfile.objects.create(compute_profile_id="16x128", cpu="16", memory="128")
        size = FunctionSize.objects.create(function=program, function_size="m", compute_profile=profile)
        job = Job.objects.create(
            author=user,
            program=program,
            runner=Program.FLEETS,
            instance_crn="crn:v1:bluemix:public:quantum-computing:us-east:a/acct:inst::",
            function_size=size,
            status=Job.PENDING,
        )

        job.change_status(
            origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS, status=Job.SUCCEEDED
        )

        rows = list(Outbox.objects.filter(job=job, channel="billing"))
        assert len(rows) == 2
        metric_types = {row.payload["data"]["metric_type"] for row in rows}
        assert any(m.startswith("license_") for m in metric_types)
        assert any(m.startswith("classical") for m in metric_types)

    def test_stopped_while_still_queued_enqueues_only_the_billing_event(self, user):
        provider = Provider.objects.create(name="ibm-dev")
        program = Program.objects.create(
            title="my-fn", author=user, entrypoint="main.py", runner=Program.FLEETS, provider=provider
        )
        job = Job.objects.create(
            author=user,
            program=program,
            runner=Program.FLEETS,
            instance_crn="crn:v1:bluemix:public:quantum-computing:us-east:a/acct:inst::",
            status=Job.QUEUED,
        )

        job.change_status(origin=JobEventOrigin.API, context=JobEventContext.STOP_JOB, status=Job.STOPPED)

        rows = list(Outbox.objects.filter(job=job, channel="billing"))
        assert len(rows) == 1
        assert rows[0].payload["data"]["metric_value"] == 0

    def test_failed_after_running_enqueues_both_messages(self, user):
        provider = Provider.objects.create(name="ibm-dev")
        program = Program.objects.create(
            title="my-fn", author=user, entrypoint="main.py", runner=Program.FLEETS, provider=provider
        )
        profile = ComputeProfile.objects.create(compute_profile_id="16x128", cpu="16", memory="128")
        size = FunctionSize.objects.create(function=program, function_size="m", compute_profile=profile)
        job = Job.objects.create(
            author=user,
            program=program,
            runner=Program.FLEETS,
            instance_crn="crn:v1:bluemix:public:quantum-computing:us-east:a/acct:inst::",
            function_size=size,
            status=Job.PENDING,
        )
        job.change_status(
            origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS, status=Job.RUNNING
        )
        Outbox.objects.filter(job=job).delete()  # RUNNING must not have enqueued anything; clear defensively

        job.change_status(origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS, status=Job.FAILED)

        assert Outbox.objects.filter(job=job, channel="billing").count() == 2

    def test_running_transition_enqueues_nothing(self, user):
        provider = Provider.objects.create(name="ibm-dev")
        program = Program.objects.create(
            title="my-fn", author=user, entrypoint="main.py", runner=Program.FLEETS, provider=provider
        )
        job = Job.objects.create(
            author=user,
            program=program,
            runner=Program.FLEETS,
            instance_crn="crn:v1:bluemix:public:quantum-computing:us-east:a/acct:inst::",
            status=Job.PENDING,
        )

        job.change_status(
            origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS, status=Job.RUNNING
        )

        assert Outbox.objects.filter(job=job).count() == 0

    def test_filler_job_enqueues_nothing_even_terminal(self, user):
        job = Job.objects.create(
            author=user,
            runner=Program.FLEETS,
            filler=True,
            instance_crn="crn:v1:bluemix:public:quantum-computing:us-east:a/acct:inst::",
            status=Job.RUNNING,
        )

        job.change_status(origin=JobEventOrigin.SCHEDULER, context=JobEventContext.FILLER_STOP, status=Job.STOPPED)

        assert Outbox.objects.filter(job=job).count() == 0

    def test_ray_job_enqueues_nothing(self, user):
        job = Job.objects.create(author=user, runner=Program.RAY, status=Job.PENDING)

        job.change_status(origin=JobEventOrigin.API, context=JobEventContext.STOP_JOB, status=Job.STOPPED)

        assert Outbox.objects.filter(job=job).count() == 0

    def test_fleets_job_without_instance_crn_enqueues_nothing(self, user):
        job = Job.objects.create(author=user, runner=Program.FLEETS, instance_crn=None, status=Job.PENDING)

        job.change_status(origin=JobEventOrigin.API, context=JobEventContext.STOP_JOB, status=Job.STOPPED)

        assert Outbox.objects.filter(job=job).count() == 0

    def test_function_without_provider_enqueues_only_the_billing_event(self, user):
        program = Program.objects.create(title="my-fn", author=user, entrypoint="main.py", runner=Program.FLEETS)
        job = Job.objects.create(
            author=user,
            program=program,
            runner=Program.FLEETS,
            instance_crn="crn:v1:bluemix:public:quantum-computing:us-east:a/acct:inst::",
            status=Job.PENDING,
        )

        job.change_status(
            origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS, status=Job.SUCCEEDED
        )

        rows = list(Outbox.objects.filter(job=job, channel="billing"))
        assert len(rows) == 1
        assert rows[0].payload["data"]["metric_type"].startswith("classical")
