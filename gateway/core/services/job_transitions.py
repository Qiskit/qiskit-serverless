"""Every job status change goes through JobTransitionService, and so does everything a status change owes.

Each public method is one transition (or, for running_to_running, the periodic progress of a job that stays
RUNNING), and it does the status change plus whatever that transition needs, so a caller cannot forget it:

- What must not be lost is stored in the Outbox table inside the same database transaction as the status
  change, and the scheduler sends it later (see specs/OUTBOX.md).
- What is best effort is sent to Kafka right after that transaction, and dropped with a log if it fails. The
  intermediate status of a mirrored job (Pending, Running, Stopping) is also sent to the Runtime API after that
  transaction. It is dropped with a log if it cannot be sent, except for a database outage, which is re-raised.
"""

import logging
from datetime import datetime, timezone

from django.db import transaction

from core.domain.billing_events import BillingEvents
from core.domain.crn import Crn
from core.domain.exceptions.invalid_job_transition_exception import InvalidJobTransitionException
from core.domain.workload_payload import build_workload_payload, is_mirrored
from core.external_call_metrics import (
    JOB_IN_PROGRESS_EVENT,
    JOB_TRANSITION_PENDING_TO_RUNNING,
    JOB_TRANSITION_QUEUED_TO_PENDING,
    JOB_TRANSITION_TO_TERMINAL,
    observe_operation,
    observer_method,
)
from core.ibm_cloud.event_streams.kafka_sender import build_kafka_sender
from core.ibm_cloud.sender import Sender
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from core.models import Job, JobEvent, Outbox, OutboxChannel, Program, WorkloadMirror
from core.services.runners import get_runner, AbstractRunner, RunnerRetryableError
from core.services.workload_best_effort_mirror import NoOpWorkloadMirror, WorkloadMirrorSender

logger = logging.getLogger("core.JobTransitionService")

# The job was already moved by someone else (a user stopped it): an expected race, recorded as rejected and not error.
_REJECTED = (InvalidJobTransitionException,)


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


class FleetAppearedError(RunnerRetryableError):
    """The job's ``fleet_id`` changed while a stop was deciding, so nothing was written."""


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
        Job.QUEUED: {Job.PENDING, Job.FAILED, Job.STOPPED, Job.STOPPING},
        Job.PENDING: {Job.SUCCEEDED, Job.FAILED, Job.STOPPED, Job.STOPPING, Job.RUNNING},
        Job.RUNNING: {Job.SUCCEEDED, Job.FAILED, Job.STOPPED, Job.STOPPING},
        # a job can finish or fail while its cancel is in flight
        Job.STOPPING: {Job.SUCCEEDED, Job.FAILED, Job.STOPPED},
        # terminal states have no next valid state
        Job.SUCCEEDED: set(),
        Job.FAILED: set(),
        Job.STOPPED: set(),
    }

    def __init__(self, billing_sender: Sender | None = None, workload_mirror: WorkloadMirrorSender | None = None):
        """
        Billing events and workloads mirror are sent through Outbox to ensure their delivery.

        However, there are other kinds of billing events and workloads that are "best effort": we try to send them
        but if the sending fails, they are ignored.

            - billing_sender best effort billing messages. It uses EVENT_STREAMS_ENABLED (Scheduler uses
            KafkaSender, which sends without wait, and Gateway (stop jobs only) uses NoOpSender).

            - workload_mirror. Used only for the intermediate statuses to the Runtime API. Scheduler uses
            WorkloadBackgroundMirror (needs a background executer), Gateway uses WorkloadInlineMirror (same thread).

        """

        self.billing_sender = billing_sender if billing_sender is not None else build_kafka_sender()
        self.workload_mirror = workload_mirror if workload_mirror is not None else NoOpWorkloadMirror()

    @observer_method(JOB_TRANSITION_QUEUED_TO_PENDING, rejected_by=_REJECTED)
    def queued_to_pending(
        self, job: Job, *, origin: JobEventOrigin, context: JobEventContext, job_fields: dict | None = None
    ) -> JobEvent:
        """The job was submitted to its runner. Nothing else is owed."""
        with transaction.atomic():
            event = self._change_status(job, Job.PENDING, origin=origin, context=context, job_fields=job_fields)
        self.workload_mirror.send(job)
        return event

    @observer_method(JOB_TRANSITION_PENDING_TO_RUNNING, rejected_by=_REJECTED)
    def pending_to_running(
        self, job: Job, *, origin: JobEventOrigin, context: JobEventContext, job_fields: dict | None = None
    ) -> JobEvent:
        """The job started running: a job_started event is sent, best effort, once it is written."""
        with transaction.atomic():
            event = self._change_status(job, Job.RUNNING, origin=origin, context=context, job_fields=job_fields)
        # A job reaches RUNNING only once, so this event is its start time
        self._send_job_in_progress(job, job_started=True, job_started_at=event.created)
        self.workload_mirror.send(job)
        return event

    def running_to_running(self, job: Job, job_started_at: datetime | None) -> None:
        """The job is still running. It is not a transition: no status or JobEvent is written, only a
        best effort in-progress event is sent."""
        with observe_operation(JOB_IN_PROGRESS_EVENT, enabled=not job.filler):
            self._send_job_in_progress(job, job_started=False, job_started_at=job_started_at)

    def stop(
        self,
        job: Job,
        *,
        origin: JobEventOrigin,
        context: JobEventContext,
        runner: AbstractRunner | None = None,
    ) -> str:
        """Stop a Fleets job and return the status written. The cancel runs before the transaction.

        Args:
            runner: Reuse this runner instead of building one, so a retrying caller fetches the IAM
                token once.

        Returns:
            ``Job.STOPPING`` when a cancel is in flight, ``Job.STOPPED`` when there was nothing to
            cancel.

        Raises:
            ValueError: If the job is not a Fleets job.
            RunnerError: If the cancel could not be delivered.
            RunnerRetryableError: If Code Engine could not be reached.
            FleetAppearedError: If a fleet appeared while this was deciding. Nothing is written,
                so the caller asks again with the fresh row and cancels that fleet.
            InvalidJobTransitionException: If the row left a status the new one is reachable from.
            OperationalError, InterfaceError: From the workload mirror, after the STOPPING status was written.
        """
        if job.runner != Program.FLEETS:
            raise ValueError(f"Job {job.id}: stop is for Fleets jobs, got runner={job.runner}")

        if job.fleet_id and (runner or get_runner(job)).stop():
            with transaction.atomic():
                self._change_status(job, Job.STOPPING, origin=origin, context=context, job_fields=None)
            self.workload_mirror.send(job)
            return Job.STOPPING

        # No fleet, or Code Engine says it is already gone. End the job only while that still
        # holds: comparing against job.fleet_id, not None, keeps the already-gone case correct.
        with transaction.atomic():
            current_fleet_id = Job.objects.select_for_update().values_list("fleet_id", flat=True).get(pk=job.pk)
            if current_fleet_id != job.fleet_id:
                # Adopt it, or the retry reads the same stale None and decides the same way again.
                job.fleet_id = current_fleet_id
                raise FleetAppearedError(f"Job {job.id}: a fleet appeared while stopping")
            self._change_status(job, Job.STOPPED, origin=origin, context=context, job_fields=None)
            self._enqueue_workload(job)
        return Job.STOPPED

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

    @observer_method(JOB_TRANSITION_TO_TERMINAL, rejected_by=_REJECTED)
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
            self._enqueue_workload(job)
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

    @observer_method(JOB_TRANSITION_TO_TERMINAL, rejected_by=_REJECTED)
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
            self._enqueue_workload(job)
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
        # The size is the snapshot, so a size row renamed or deleted after creation no longer changes the fee.
        # A job created by a pod that predates the snapshot (during a rollout) has none and uses its size row.
        # Only a job with neither is waived. This goes away once function_size_name stops being nullable
        # (tracked by @ElePT). If the function_size FK is removed instead, that migration must backfill the
        # remaining null function_size_name values from the FK row's label BEFORE the RemoveField operation,
        # because the label is lost once the column is dropped. Then size_label can read only the snapshot.
        if job.size_label is None:
            logger.error(
                "job_id=%s license fee message cannot be built for provider=%s: the job has no size, "
                "waiving the fee",
                job.id,
                job.program.provider,
            )
            return

        message = BillingEvents.build_license_fee(job, job_started_at)
        Outbox.objects.create(job=job, channel=OutboxChannel.LICENSE_FEE, region=self._region(job), payload=message)

    def _enqueue_workload(self, job: Job) -> None:
        """The final status of a mirrored job, to send it to the Runtime API. If the payload builder rejects the job
        (it has no program), the error reaches the caller and the transition is rolled back. This is the last step of
        the mirror, so the job leaves the WorkloadMirror table: the outbox row carries the payload and nothing reads
        the table after a terminal status."""
        if is_mirrored(job):
            payload = build_workload_payload(job)
            Outbox.objects.create(job=job, channel=OutboxChannel.WORKLOAD, region=self._region(job), payload=payload)
            WorkloadMirror.objects.filter(job_id=job.id).delete()

    def _send_job_in_progress(self, job: Job, job_started: bool, job_started_at: datetime | None) -> None:
        """Best effort: a failure is logged and the event is dropped, it never reaches the caller.

        The sender is asked not to wait for the broker (timeout=0): it does not raise for a message it cannot
        route, queue or deliver, it counts it and logs it in aggregate.

        A job transitioning to terminal in this same scheduler tick will produce both an in-progress and a
        completed event; consumers key on the job_started / job_completed flags.
        """
        if job.filler:
            return
        try:
            job_last_progress_time = None if job_started else datetime.now(timezone.utc)
            payload = BillingEvents.build_job_usage(job, job_started_at, job_last_progress_time)
            # timeout=0: send and return at once, without waiting for the ack or a flush. It never raises error,
            # but it is caught anyway in case a sender implementation changes in the future
            self.billing_sender.send(payload, timeout=0)
        except RuntimeError as ex:
            # never expected: the sender already drops and logs its own failures
            logger.error(
                "job_id=%s error emitting job_in_progress event to Kafka, event dropped: %s",
                job.id,
                str(ex),
            )
