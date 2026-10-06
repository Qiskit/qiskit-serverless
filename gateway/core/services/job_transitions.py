"""Every job status change goes through JobTransitionService, and so does everything a status change owes.

Each public method is one transition (or, for running_to_running, the periodic progress of a job that stays
RUNNING), and it does the status change plus whatever that transition needs, so a caller cannot forget it:

- What must not be lost is stored in the Outbox table inside the same database transaction as the status
  change, and the scheduler sends it later (see specs/OUTBOX.md).
- What is best effort is sent to Kafka right after that transaction, and dropped with a log if it fails.
"""

import logging
from datetime import datetime, timezone

from django.db import transaction

from core.domain.billing_events import BillingEvents
from core.domain.crn import Crn
from core.domain.exceptions.invalid_job_transition_exception import InvalidJobTransitionException
from core.ibm_cloud.event_streams.kafka_sender import build_kafka_sender
from core.ibm_cloud.sender import Sender
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from core.models import Job, JobEvent, Outbox, OutboxChannel, Program

logger = logging.getLogger("core.JobTransitionService")


def _is_usage_billable(job: Job) -> bool:
    """Only real Fleets jobs (no filler) with an instance CRN are billed."""
    return job.runner == Program.FLEETS and not job.filler and bool(job.instance_crn)


def _is_fee_billable(job: Job) -> bool:
    """The license fee is only owed for a function with a provider."""
    return (
        job.runner == Program.FLEETS
        and not job.filler
        and bool(job.instance_crn)
        and bool(job.program and job.program.provider)
    )


class JobTransitionService:
    """Changes the status of a job, validated and atomic, and does what each transition owes.

    Every transition method raises InvalidJobTransitionException if the job, read fresh from the database
    under a lock, is not in a status that allows it (like a job stopped by the user while the scheduler
    was about to mark it as SUCCEEDED). Each caller decides what "already terminal" means for it.

    Do not call it from inside another transaction: the best effort events are sent right after the
    transaction of the transition, without waiting for the outer one to commit.
    """

    # Valid next status per current status
    VALID_TRANSITIONS: dict[str, set[str]] = {
        # valid next state for non-terminal states
        Job.QUEUED: {Job.PENDING, Job.FAILED, Job.STOPPED},
        Job.PENDING: {Job.SUCCEEDED, Job.FAILED, Job.STOPPED, Job.RUNNING},
        Job.RUNNING: {Job.SUCCEEDED, Job.FAILED, Job.STOPPED},
        # terminal states have no next valid state
        Job.SUCCEEDED: set(),
        Job.FAILED: set(),
        Job.STOPPED: set(),
    }

    def __init__(self, sender: Sender | None = None):
        """The sender of the best effort events.
        By default, it creates the sender based on EVENT_STREAMS_ENABLED (so the scheduler has KafkaSender, and
        the Gateway (stop jobs only) has NoOpSender)"""
        self.sender = sender if sender is not None else build_kafka_sender()

    def queued_to_pending(
        self, job: Job, *, origin: JobEventOrigin, context: JobEventContext, job_fields: dict | None = None
    ) -> JobEvent:
        """The job was submitted to its runner. Nothing else is owed."""
        with transaction.atomic():
            return self._change_status(job, Job.PENDING, origin=origin, context=context, job_fields=job_fields)

    def pending_to_running(
        self, job: Job, *, origin: JobEventOrigin, context: JobEventContext, job_fields: dict | None = None
    ) -> JobEvent:
        """The job started running: a job_started event is sent, best effort, once it is written."""
        with transaction.atomic():
            event = self._change_status(job, Job.RUNNING, origin=origin, context=context, job_fields=job_fields)
        self._send_job_in_progress(job, job_started=True)
        return event

    def running_to_running(self, job: Job) -> None:
        """The job is still running. It is not a transition: no status or JobEvent is written, only a
        best effort in-progress event is sent."""
        self._send_job_in_progress(job, job_started=False)

    def to_terminal(
        self, job: Job, status: str, *, origin: JobEventOrigin, context: JobEventContext, job_fields: dict | None = None
    ) -> JobEvent:
        """to_succeeded, to_failed or to_stopped, for the caller that only knows the final status."""
        transition = {
            Job.SUCCEEDED: self.to_succeeded,
            Job.FAILED: self.to_failed,
            Job.STOPPED: self.to_stopped,
        }.get(status)
        if transition is None:
            raise ValueError(f"Job {job.id}: {status} is not a terminal status")
        return transition(job, origin=origin, context=context, job_fields=job_fields)

    def to_succeeded(
        self, job: Job, *, origin: JobEventOrigin, context: JobEventContext, job_fields: dict | None = None
    ) -> JobEvent:
        """The job finished. A job cannot succeed without having run, so its license fee is always owed."""
        with transaction.atomic():
            event = self._change_status(job, Job.SUCCEEDED, origin=origin, context=context, job_fields=job_fields)
            if _is_usage_billable(job):
                job_started_at = JobEvent.objects.first_running_at(job.id)
                self._enqueue_job_usage(job, job_started_at, event.created)
                if _is_fee_billable(job):
                    self._enqueue_license_fee(job, job_started_at)
        return event

    def to_failed(
        self, job: Job, *, origin: JobEventOrigin, context: JobEventContext, job_fields: dict | None = None
    ) -> JobEvent:
        """The job failed."""
        return self.to_stopped_or_failed(job, Job.FAILED, origin=origin, context=context, job_fields=job_fields)

    def to_stopped(
        self, job: Job, *, origin: JobEventOrigin, context: JobEventContext, job_fields: dict | None = None
    ) -> JobEvent:
        """The job was stopped, by a user or by the scheduler."""
        return self.to_stopped_or_failed(job, Job.STOPPED, origin=origin, context=context, job_fields=job_fields)

    def to_stopped_or_failed(
        self, job: Job, status: str, *, origin: JobEventOrigin, context: JobEventContext, job_fields: dict | None
    ) -> JobEvent:
        """Called only when failed or stopped"""
        with transaction.atomic():
            event = self._change_status(job, status, origin=origin, context=context, job_fields=job_fields)
            if _is_usage_billable(job):
                job_started_at = JobEvent.objects.first_running_at(job.id)
                self._enqueue_job_usage(job, job_started_at, event.created)
                # 1899 Failed or stopped job may never have executed, so it sends fee if, and only if, it was RUNNING
                if job_started_at is not None and _is_fee_billable(job):
                    self._enqueue_license_fee(job, job_started_at)
        return event

    def _change_status(
        self,
        job: Job,
        status: str,
        *,
        origin: JobEventOrigin,
        context: JobEventContext,
        job_fields: dict | None,
    ) -> JobEvent:
        """
        Transition the job's status, validating the state change is valid. It must run inside a transaction,
        so whatever the caller stores next commits or rolls back together with the status change.

        Steps:
            - LOCK: Lock the job by id (Django raises if there is no transaction open)
            - Reads the job status again fresh from db and validate the transition
            - Adds a new JobEvent
            - Changes the job status + extra fields
        """
        current_status = Job.objects.select_for_update().values_list("status", flat=True).get(pk=job.pk)

        if status not in self.VALID_TRANSITIONS.get(current_status, set()):
            raise InvalidJobTransitionException(f"Job {job.id}: invalid transition {current_status} -> {status}")

        event = JobEvent.objects.add_status_event(job_id=job.id, origin=origin, context=context, status=status)
        job.update_fields({"status": status, **(job_fields or {})})
        return event

    @staticmethod
    def _region(job: Job) -> str | None:
        """The region of the job's instance CRN, or None when it has none."""
        crn = Crn.parse(job.instance_crn)
        return crn.region if crn else None

    def _enqueue_job_usage(self, job: Job, job_started_at: datetime | None, job_finished_time: datetime) -> None:
        """The final usage event: always owed, whatever the job's outcome."""
        message = BillingEvents.build_job_completed_event(job, job_started_at, job_finished_time)
        Outbox.objects.create(job=job, channel=OutboxChannel.JOB_USAGE, region=self._region(job), payload=message)

    def _enqueue_license_fee(self, job: Job, job_started_at: datetime | None) -> None:
        """The license fee message. The caller has checked the job owes it."""
        # This branch goes away once function_size stops being nullable (tracked by @ElePT).
        if job.function_size is None:
            logger.error(
                "job_id=%s license fee message cannot be built for provider=%s: function_size is missing, "
                "waiving the fee",
                job.id,
                job.program.provider,
            )
            return

        message = BillingEvents.build_license_fee(job, job_started_at)
        Outbox.objects.create(job=job, channel=OutboxChannel.LICENSE_FEE, region=self._region(job), payload=message)

    def _send_job_in_progress(self, job: Job, job_started: bool) -> None:
        """Best effort: a failure is logged and the event is dropped, it never reaches the caller.

        The sender is asked not to wait for the broker (timeout=0): it does not raise for a message it cannot
        route, queue or deliver, it counts it and logs it in aggregate.

        A job transitioning to terminal in this same scheduler tick will produce both an in-progress and a
        completed event; consumers key on the job_started / job_completed flags.
        """
        try:
            if job.filler:
                return
            job_started_at = JobEvent.objects.first_running_at(job.id)
            job_last_progress_time = None if job_started else datetime.now(timezone.utc)
            payload = BillingEvents.build_job_usage(job, job_started_at, job_last_progress_time)
            self.sender.send(payload, timeout=0)
        except RuntimeError as ex:
            logger.error(
                "job_id=%s error emitting job_in_progress event to Kafka, event dropped: %s",
                job.id,
                str(ex),
            )
