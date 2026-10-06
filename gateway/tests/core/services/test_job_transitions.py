"""Tests for JobTransitionService: the status change of every transition and what each one owes."""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User

from core.domain.exceptions.invalid_job_transition_exception import InvalidJobTransitionException
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from core.models import ComputeProfile, FunctionSize, Job, JobEvent, Outbox, OutboxChannel, Program, Provider
from core.services.job_transitions import JobTransitionService

pytestmark = pytest.mark.django_db

CRN = "crn:v1:bluemix:public:quantum-computing:us-east:a/acct:inst::"


def _licensed_fleets_job(user, status, fleet_id="fleet-abc"):
    """A Fleets job of a function with a provider and a size: it can owe both billing messages."""
    provider = Provider.objects.create(name=f"ibm-dev-{uuid.uuid4().hex[:8]}")
    program = Program.objects.create(
        title="my-fn", author=user, entrypoint="main.py", runner=Program.FLEETS, provider=provider
    )
    profile = ComputeProfile.objects.create(compute_profile_id=f"p-{uuid.uuid4().hex[:8]}", cpu="16", memory="128")
    size = FunctionSize.objects.create(function=program, function_size="m", compute_profile=profile)
    return Job.objects.create(
        author=user,
        program=program,
        runner=Program.FLEETS,
        instance_crn=CRN,
        function_size=size,
        status=status,
        fleet_id=fleet_id,
    )


@pytest.fixture
def user():
    return User.objects.create_user(username="author")


@pytest.fixture
def sender():
    return MagicMock()


@pytest.fixture
def service(sender):
    return JobTransitionService(sender=sender)


class TestTransition:
    """Unit tests for the status change every JobTransitionService transition does."""

    def test_persists_status_and_job_fields(self, service):
        author = User.objects.create_user(username="change-status-author-1")
        job = Job.objects.create(author=author, status=Job.PENDING)

        service.pending_to_running(
            job,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.UPDATE_JOB_STATUS,
            job_fields={"sub_status": "mapping"},
        )

        job.refresh_from_db()
        assert job.status == Job.RUNNING
        assert job.sub_status == "mapping"

    def test_creates_the_status_change_event(self, service):
        author = User.objects.create_user(username="change-status-author-2")
        job = Job.objects.create(author=author, status=Job.RUNNING)

        event = service.to_stopped(job, origin=JobEventOrigin.API, context=JobEventContext.STOP_JOB)

        assert event.data == {"status": Job.STOPPED}
        assert event.origin == JobEventOrigin.API
        assert event.context == JobEventContext.STOP_JOB

    def test_rolls_back_the_event_if_the_job_write_fails(self, service, monkeypatch):
        """Event-then-job must be all-or-nothing: a failed job write must not leave
        a JobEvent behind with no matching state change."""
        author = User.objects.create_user(username="change-status-author-3")
        job = Job.objects.create(author=author, status=Job.PENDING)

        def _boom(self, fields_map):  # pylint: disable=unused-argument
            raise RuntimeError("boom")

        monkeypatch.setattr(Job, "update_fields", _boom)

        with pytest.raises(RuntimeError, match="boom"):
            service.pending_to_running(job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS)

        assert JobEvent.objects.filter(job=job).count() == 0

    def test_raises_when_the_job_is_already_terminal(self, service):
        """A transition on a job already in a terminal status must not overwrite it or create
        another JobEvent: the transition raises instead of writing anything, leaving it to the
        caller to decide what "already terminal" means for it."""
        author = User.objects.create_user(username="change-status-author-4")
        job = Job.objects.create(author=author, status=Job.SUCCEEDED)

        with pytest.raises(InvalidJobTransitionException):
            service.to_stopped(job, origin=JobEventOrigin.API, context=JobEventContext.STOP_JOB)

        assert Job.objects.get(pk=job.pk).status == Job.SUCCEEDED
        assert JobEvent.objects.filter(job=job).count() == 0


class TestValidatesTransitions:
    """JobTransitionService rejects any transition not listed in JobTransitionService.VALID_TRANSITIONS."""

    @pytest.mark.parametrize(
        "current_status,transition",
        [
            (Job.QUEUED, "pending_to_running"),
            (Job.QUEUED, "to_succeeded"),
            (Job.PENDING, "queued_to_pending"),
            (Job.RUNNING, "queued_to_pending"),
            (Job.RUNNING, "pending_to_running"),
            (Job.SUCCEEDED, "to_stopped"),
            (Job.FAILED, "to_failed"),
            (Job.STOPPING, "to_succeeded"),
        ],
    )
    def test_rejects_a_transition_outside_the_whitelist(self, service, current_status, transition):
        author = User.objects.create_user(username=f"invalid-transition-{current_status}-{transition}")
        job = Job.objects.create(author=author, status=current_status)

        with pytest.raises(InvalidJobTransitionException):
            getattr(service, transition)(
                job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS
            )

        assert Job.objects.get(pk=job.pk).status == current_status
        assert JobEvent.objects.filter(job=job).count() == 0


class TestBillingOutbox:
    """JobTransitionService is the only place that builds and stores outbox messages, and only for
    an eligible job (Fleets, not filler, with an instance CRN) transitioning to a terminal
    status."""

    def test_succeeded_enqueues_both_messages_even_without_a_running_event(self, service, user):
        """The short-job-between-two-polls case: never observed RUNNING, still owes the fee."""
        job = _licensed_fleets_job(user, Job.PENDING)

        service.to_succeeded(job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS)

        billing_event = Outbox.objects.get(job=job, channel=OutboxChannel.JOB_USAGE)
        license_fee = Outbox.objects.get(job=job, channel=OutboxChannel.LICENSE_FEE)
        assert billing_event.payload["data"]["metric_type"].startswith("classical")
        assert license_fee.payload["data"]["metric_type"].startswith("license_")
        assert billing_event.region == license_fee.region == "us-east"

    def test_stopped_while_still_queued_enqueues_only_the_billing_event(self, service, user):
        job = _licensed_fleets_job(user, Job.QUEUED)

        service.to_stopped(job, origin=JobEventOrigin.API, context=JobEventContext.STOP_JOB)

        billing_event = Outbox.objects.get(job=job, channel=OutboxChannel.JOB_USAGE)
        assert billing_event.payload["data"]["metric_value"] == 0
        assert not Outbox.objects.filter(job=job, channel=OutboxChannel.LICENSE_FEE).exists()

    def test_failed_after_running_enqueues_both_messages(self, service, user):
        job = _licensed_fleets_job(user, Job.PENDING)
        service.pending_to_running(job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS)
        Outbox.objects.filter(job=job).delete()  # RUNNING must not have enqueued anything; clear defensively

        service.to_failed(job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS)

        assert Outbox.objects.filter(job=job, channel=OutboxChannel.JOB_USAGE).count() == 1
        assert Outbox.objects.filter(job=job, channel=OutboxChannel.LICENSE_FEE).count() == 1

    def test_failed_without_ever_running_enqueues_only_the_billing_event(self, service, user):
        """Skipping RUNNING and ending FAILED gives no proof the job executed, so no license fee."""
        job = _licensed_fleets_job(user, Job.PENDING)

        service.to_failed(job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS)

        assert Outbox.objects.filter(job=job, channel=OutboxChannel.JOB_USAGE).count() == 1
        assert not Outbox.objects.filter(job=job, channel=OutboxChannel.LICENSE_FEE).exists()

    def test_running_transition_enqueues_nothing(self, service, user):
        job = _licensed_fleets_job(user, Job.PENDING)

        service.pending_to_running(job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS)

        assert Outbox.objects.filter(job=job).count() == 0

    def test_filler_job_enqueues_nothing_even_terminal(self, service, user):
        job = Job.objects.create(
            author=user,
            runner=Program.FLEETS,
            filler=True,
            instance_crn="crn:v1:bluemix:public:quantum-computing:us-east:a/acct:inst::",
            status=Job.RUNNING,
        )

        service.to_stopped(job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.FILLER_STOP)

        assert Outbox.objects.filter(job=job).count() == 0

    def test_ray_job_enqueues_nothing(self, service, user):
        job = Job.objects.create(author=user, runner=Program.RAY, status=Job.PENDING)

        service.to_stopped(job, origin=JobEventOrigin.API, context=JobEventContext.STOP_JOB)

        assert Outbox.objects.filter(job=job).count() == 0

    def test_fleets_job_without_instance_crn_enqueues_nothing(self, service, user):
        job = Job.objects.create(author=user, runner=Program.FLEETS, instance_crn=None, status=Job.PENDING)

        service.to_stopped(job, origin=JobEventOrigin.API, context=JobEventContext.STOP_JOB)

        assert Outbox.objects.filter(job=job).count() == 0

    def test_a_malformed_instance_crn_enqueues_the_row_without_a_region(self, service, user):
        job = Job.objects.create(author=user, runner=Program.FLEETS, instance_crn="not-a-crn", status=Job.PENDING)

        service.to_stopped(job, origin=JobEventOrigin.API, context=JobEventContext.STOP_JOB)

        assert Outbox.objects.get(job=job, channel=OutboxChannel.JOB_USAGE).region is None

    def test_function_without_provider_enqueues_only_the_billing_event(self, service, user):
        program = Program.objects.create(title="my-fn", author=user, entrypoint="main.py", runner=Program.FLEETS)
        job = Job.objects.create(
            author=user,
            program=program,
            runner=Program.FLEETS,
            instance_crn="crn:v1:bluemix:public:quantum-computing:us-east:a/acct:inst::",
            status=Job.PENDING,
        )

        service.to_succeeded(job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS)

        billing_event = Outbox.objects.get(job=job, channel=OutboxChannel.JOB_USAGE)
        assert billing_event.payload["data"]["metric_type"].startswith("classical")
        assert not Outbox.objects.filter(job=job, channel=OutboxChannel.LICENSE_FEE).exists()

    def test_missing_function_size_despite_a_provider_waives_the_fee_and_logs(self, service, user, caplog):
        """A SET_NULL deletion of FunctionSize racing the transition is an anomaly, not the
        normal no-provider case, so it gets a log line even though the fee is waived the same way."""
        job = _licensed_fleets_job(user, Job.PENDING)
        Job.objects.filter(pk=job.pk).update(function_size=None)
        job.refresh_from_db()

        with caplog.at_level(logging.ERROR):
            service.to_succeeded(job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS)

        assert not Outbox.objects.filter(job=job, channel=OutboxChannel.LICENSE_FEE).exists()
        assert "waiving the fee" in caplog.text

    def test_second_terminal_transition_enqueues_nothing_more(self, service, user):
        """A job that reaches a terminal status twice must only be billed once, and the second
        transition must not overwrite its status or create a second JobEvent."""
        job = _licensed_fleets_job(user, Job.PENDING)

        service.to_succeeded(job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS)
        rows_after_first = Outbox.objects.filter(job=job).count()
        events_after_first = JobEvent.objects.filter(job=job).count()

        with pytest.raises(InvalidJobTransitionException):
            service.to_stopped(job, origin=JobEventOrigin.API, context=JobEventContext.STOP_JOB)

        assert Outbox.objects.filter(job=job).count() == rows_after_first
        assert JobEvent.objects.filter(job=job).count() == events_after_first
        assert Job.objects.get(pk=job.pk).status == Job.SUCCEEDED

    def test_stopped_after_running_enqueues_both_messages(self, user, service):
        job = _licensed_fleets_job(user, Job.PENDING)
        service.pending_to_running(job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS)

        service.to_stopped(job, origin=JobEventOrigin.API, context=JobEventContext.STOP_JOB)

        assert Outbox.objects.filter(job=job, channel=OutboxChannel.JOB_USAGE).count() == 1
        assert Outbox.objects.filter(job=job, channel=OutboxChannel.LICENSE_FEE).count() == 1

    def test_failed_while_still_queued_enqueues_only_the_billing_event(self, user, service):
        """A submission that failed never ran: usage is reported (zero seconds) but no license fee is owed."""
        job = _licensed_fleets_job(user, Job.QUEUED)

        service.to_failed(job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.SCHEDULE_JOBS)

        assert Outbox.objects.filter(job=job, channel=OutboxChannel.JOB_USAGE).count() == 1
        assert not Outbox.objects.filter(job=job, channel=OutboxChannel.LICENSE_FEE).exists()

    def test_a_failing_outbox_write_rolls_back_the_status_and_the_event(self, user, service, monkeypatch):
        job = _licensed_fleets_job(user, Job.PENDING)

        def _boom(*args, **kwargs):
            raise RuntimeError("outbox down")

        monkeypatch.setattr(Outbox.objects, "create", _boom)

        with pytest.raises(RuntimeError, match="outbox down"):
            service.to_succeeded(job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS)

        assert Job.objects.get(pk=job.pk).status == Job.PENDING
        assert JobEvent.objects.filter(job=job).count() == 0
        assert Outbox.objects.filter(job=job).count() == 0


class TestSender:
    """The default sender creates the Kafka producers, so it is only built when none is given."""

    def test_builds_the_default_sender_only_when_none_is_given(self):
        with patch("core.services.job_transitions.build_kafka_sender") as build_sender:
            given = MagicMock()
            assert JobTransitionService(sender=given).sender is given
            build_sender.assert_not_called()

            assert JobTransitionService().sender is build_sender.return_value
            build_sender.assert_called_once_with()


class TestToTerminal:
    """to_terminal is to_succeeded, to_failed and to_stopped for the caller that only knows the final status."""

    @pytest.mark.parametrize("status", [Job.SUCCEEDED, Job.FAILED, Job.STOPPED])
    def test_writes_the_given_terminal_status(self, service, user, status):
        job = Job.objects.create(author=user, runner=Program.RAY, status=Job.RUNNING)

        service.to_terminal(job, status, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS)

        assert Job.objects.get(pk=job.pk).status == status

    def test_bills_like_the_named_transitions(self, service, user):
        job = Job.objects.create(author=user, runner=Program.FLEETS, instance_crn=CRN, status=Job.RUNNING)

        service.to_terminal(job, Job.FAILED, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS)

        assert Outbox.objects.filter(job=job, channel=OutboxChannel.JOB_USAGE).count() == 1

    @pytest.mark.parametrize("status", [Job.QUEUED, Job.PENDING, Job.RUNNING])
    def test_rejects_a_status_that_is_not_terminal(self, service, user, status):
        job = Job.objects.create(author=user, status=Job.QUEUED)

        with pytest.raises(ValueError):
            service.to_terminal(job, status, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.SCHEDULE_JOBS)

        assert Job.objects.get(pk=job.pk).status == Job.QUEUED


class TestBestEffortEvents:
    """The in-progress events are sent to Kafka once the transition is written, and never break it."""

    @pytest.fixture
    def fleets_job(self, user):
        program = Program.objects.create(title="my-fn", author=user, entrypoint="main.py", runner=Program.FLEETS)
        profile = ComputeProfile.objects.create(compute_profile_id="16x128", cpu="16", memory="128")
        return Job.objects.create(
            author=user,
            program=program,
            runner=Program.FLEETS,
            instance_crn=CRN,
            compute_profile_fk=profile,
            status=Job.PENDING,
        )

    def test_pending_to_running_sends_job_started(self, service, sender, fleets_job):
        service.pending_to_running(
            fleets_job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS
        )

        sender.send.assert_called_once()
        data = sender.send.call_args[0][0]["data"]
        assert data["job_started"] is True
        assert data["job_completed"] is False

    def test_job_started_is_sent_after_the_status_is_written(self, service, sender, fleets_job):
        seen = []
        sender.send.side_effect = lambda payload: seen.append(Job.objects.get(pk=fleets_job.pk).status)

        service.pending_to_running(
            fleets_job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS
        )

        assert seen == [Job.RUNNING]

    def test_a_transition_that_does_not_happen_sends_nothing(self, service, sender, fleets_job):
        Job.objects.filter(pk=fleets_job.pk).update(status=Job.STOPPED)

        with pytest.raises(InvalidJobTransitionException):
            service.pending_to_running(
                fleets_job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS
            )

        sender.send.assert_not_called()

    def test_a_kafka_failure_on_job_started_does_not_undo_the_transition(self, service, sender, fleets_job):
        sender.send.side_effect = RuntimeError("kafka down")

        service.pending_to_running(
            fleets_job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS
        )  # must not raise

        assert Job.objects.get(pk=fleets_job.pk).status == Job.RUNNING

    def test_running_to_running_sends_progress_without_writing_anything(self, service, sender, fleets_job):
        Job.objects.filter(pk=fleets_job.pk).update(status=Job.RUNNING)
        fleets_job.refresh_from_db()
        JobEvent.objects.add_status_event(
            job_id=fleets_job.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.UPDATE_JOB_STATUS,
            status=Job.RUNNING,
        )
        events_before = JobEvent.objects.filter(job=fleets_job).count()

        service.running_to_running(fleets_job)

        sender.send.assert_called_once()
        data = sender.send.call_args[0][0]["data"]
        assert data["job_started"] is False
        assert data["job_completed"] is False
        assert JobEvent.objects.filter(job=fleets_job).count() == events_before
        assert Job.objects.get(pk=fleets_job.pk).status == Job.RUNNING

    def test_a_kafka_failure_is_logged_and_does_not_reach_the_caller(self, service, sender, fleets_job, caplog):
        sender.send.side_effect = RuntimeError("kafka down")
        Job.objects.filter(pk=fleets_job.pk).update(status=Job.RUNNING)
        JobEvent.objects.add_status_event(
            job_id=fleets_job.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.UPDATE_JOB_STATUS,
            status=Job.RUNNING,
        )

        with caplog.at_level(logging.ERROR):
            service.running_to_running(fleets_job)  # must not raise

        assert "event dropped" in caplog.text
        assert "kafka down" in caplog.text

    def test_a_filler_job_sends_nothing(self, service, sender, fleets_job):
        Job.objects.filter(pk=fleets_job.pk).update(filler=True)
        fleets_job.refresh_from_db()

        service.running_to_running(fleets_job)

        sender.send.assert_not_called()

    def test_queued_to_pending_and_the_terminal_transitions_send_nothing_to_kafka_directly(self, service, sender, user):
        job = Job.objects.create(author=user, runner=Program.FLEETS, instance_crn=CRN, status=Job.QUEUED)

        service.queued_to_pending(job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.SCHEDULE_JOBS)
        service.to_succeeded(job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS)

        sender.send.assert_not_called()


@patch("core.services.job_transitions.get_runner")
class TestTryStop:
    """try_stop cancels the fleet and records STOPPING. The scheduler confirms it later."""

    @pytest.mark.parametrize("current_status", [Job.QUEUED, Job.PENDING, Job.RUNNING])
    def test_writes_stopping_and_its_event_and_owes_nothing(self, get_runner, service, user, current_status):
        job = _licensed_fleets_job(user, current_status)

        assert service.try_stop(job, origin=JobEventOrigin.API, context=JobEventContext.STOP_JOB) is True

        assert Job.objects.get(pk=job.pk).status == Job.STOPPING
        assert JobEvent.objects.filter(job=job, data__status=Job.STOPPING).count() == 1
        assert Outbox.objects.filter(job=job).count() == 0

    def test_leaves_sub_status_alone(self, get_runner, service, user):
        """STOPPING is in ACTIVE_STATUSES, so the running container may still patch sub_status."""
        job = _licensed_fleets_job(user, Job.RUNNING)
        Job.objects.filter(pk=job.pk).update(sub_status=Job.EXECUTING_QPU)
        job.refresh_from_db()

        service.try_stop(job, origin=JobEventOrigin.API, context=JobEventContext.STOP_JOB)

        assert Job.objects.get(pk=job.pk).sub_status == Job.EXECUTING_QPU

    def test_a_ray_job_raises(self, get_runner, service, user):
        """STOPPING is Fleets only, because the Ray poller would push the row back to RUNNING. Callers
        fork on the runner before this, so a Ray job here is a caller bug, not a runtime condition.

        The fleet_id is deliberately set, so this pins the runner check and not the no-fleet one.
        """
        program = Program.objects.create(title="ray-fn", author=user, entrypoint="main.py", runner=Program.RAY)
        job = Job.objects.create(
            author=user, program=program, runner=Program.RAY, status=Job.RUNNING, fleet_id="fleet-abc"
        )

        with pytest.raises(ValueError, match="try_stop is for Fleets jobs"):
            service.try_stop(job, origin=JobEventOrigin.API, context=JobEventContext.STOP_JOB)

        assert Job.objects.get(pk=job.pk).status == Job.RUNNING
        assert JobEvent.objects.filter(job=job).count() == 0
        get_runner.assert_not_called()

    def test_a_job_with_no_fleet_is_refused(self, get_runner, service, user):
        job = _licensed_fleets_job(user, Job.QUEUED, fleet_id=None)

        assert service.try_stop(job, origin=JobEventOrigin.API, context=JobEventContext.STOP_JOB) is False

        assert Job.objects.get(pk=job.pk).status == Job.QUEUED
        get_runner.assert_not_called()

    def test_a_cancel_that_finds_nothing_writes_no_status(self, get_runner, service, user):
        """stop() answers False for a fleet Code Engine no longer has, so nothing will confirm a stop."""
        get_runner.return_value.stop.return_value = False
        job = _licensed_fleets_job(user, Job.RUNNING)

        assert service.try_stop(job, origin=JobEventOrigin.API, context=JobEventContext.STOP_JOB) is False

        assert Job.objects.get(pk=job.pk).status == Job.RUNNING
        assert JobEvent.objects.filter(job=job).count() == 0

    def test_a_job_that_ran_before_the_cancel_is_billed_up_to_the_confirmation(self, get_runner, service, user):
        """The billed window of a cancelled job ends when the scheduler confirms, not when the user asked."""
        job = _licensed_fleets_job(user, Job.RUNNING)
        JobEvent.objects.add_status_event(
            job_id=job.id,
            origin=JobEventOrigin.SCHEDULER,
            context=JobEventContext.UPDATE_JOB_STATUS,
            status=Job.RUNNING,
        )
        JobEvent.objects.filter(job=job, data__status=Job.RUNNING).update(
            created=datetime.now(timezone.utc) - timedelta(seconds=100)
        )
        service.try_stop(job, origin=JobEventOrigin.API, context=JobEventContext.STOP_JOB)

        service.to_stopped(job, origin=JobEventOrigin.SCHEDULER, context=JobEventContext.UPDATE_JOB_STATUS)

        usage = Outbox.objects.get(job=job, channel=OutboxChannel.JOB_USAGE)
        assert usage.payload["data"]["metric_value"] >= 100, "the window did not run to the confirmation"
        # A job seen in RUNNING owes the fee, so passing through STOPPING does not waive it.
        assert Outbox.objects.filter(job=job, channel=OutboxChannel.LICENSE_FEE).count() == 1
