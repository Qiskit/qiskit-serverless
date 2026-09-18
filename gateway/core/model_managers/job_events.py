"""Job events model manager."""

import logging
from typing import Any
import uuid

from enum import StrEnum

from django.db import transaction
from django.db.models import QuerySet

logger = logging.getLogger("core.JobEvents")


class JobEventOrigin(StrEnum):
    """Job events origin enum."""

    API = "API"
    SCHEDULER = "SCHEDULER"
    BACKOFFICE = "BACKOFFICE"


class JobEventContext(StrEnum):
    """Job events context enum."""

    # Gateway: new job is created in the db only (status QUEUED)
    RUN_PROGRAM = "RUN_PROGRAM"

    # Scheduler: Job is launched (status PENDING)
    SCHEDULE_JOBS = "SCHEDULE_JOBS"

    # Gateway: job status STOPPED
    STOP_JOB = "STOP_JOB"

    # Scheduler: PENDING to RUNNING, and RUNNING to FAILED/STOPPED/SUCCEEDED
    UPDATE_JOB_STATUS = "UPDATE_JOB_STATUS"

    # Gateway: status RUNNING, substatus change
    SET_SUB_STATUS = "SET_SUB_STATUS"

    # Admin: any state to any state
    SAVE_MODEL = "SAVE_MODEL"
    SEND_ERROR = "SEND_ERROR"

    # Scheduler: a filler job was created and submitted to Fleets (status PENDING or FAILED)
    FILLER_SUBMIT = "FILLER_SUBMIT"

    # Scheduler: a filler job was stopped to free capacity (status STOPPED)
    FILLER_STOP = "FILLER_STOP"

    FILLER_FAILED = "FILLER_FAILED"


class JobEventType(StrEnum):
    """Job events type enum."""

    ERROR = "ERROR"
    STATUS_CHANGE = "STATUS_CHANGE"
    SUB_STATUS_CHANGE = "SUB_STATUS_CHANGE"


class JobEventQuerySet(QuerySet):
    """Job events query set to transform into a manager."""

    def add_status_event(  # pylint:  disable=too-many-positional-arguments
        self,
        job_id: uuid.UUID,
        origin: JobEventOrigin,
        context: JobEventContext,
        status: str,
    ):
        """Status change event for jobs.

        Also updates a matching JobOutbox row if one exists (Ray, filler, and
        pre-deployment jobs have none, and the update below then touches zero
        rows). The two writes are wrapped in their own transaction so the event
        and the outbox row it drives never diverge, regardless of whether the
        caller wraps this call in a transaction of its own (nested atomic blocks
        share the same underlying database transaction via a savepoint, so this
        adds no separate commit).
        """
        from core.models import Job, JobOutbox  # pylint: disable=import-outside-toplevel, cyclic-import

        logger.info(
            "[add_status_event] job_id=%s | Set status to %s | %s %s %s",
            job_id,
            status,
            JobEventType.STATUS_CHANGE,
            origin,
            context,
        )

        with transaction.atomic():
            event = self.create(
                job_id=job_id,
                origin=origin,
                context=context,
                event_type=JobEventType.STATUS_CHANGE,
                data={"status": status},
            )

            outbox_fields = {"job_status": status, "status_changed_at": event.created}
            if status == Job.RUNNING:
                outbox_fields["has_run"] = True
            JobOutbox.objects.filter(job_id=job_id).update(**outbox_fields)

        return event

    def first_running_at(self, job_id: uuid.UUID):
        """When this job first reached RUNNING, from its own event history.

        Returns None if it never did (still queued/pending, or terminated
        without running). Ordered explicitly ascending: JobEvent.Meta.ordering
        is descending by default, and the first RUNNING event is the one that
        counts here, not the latest.
        """
        from core.models import Job  # pylint: disable=import-outside-toplevel, cyclic-import

        event = (
            self.filter(job_id=job_id, event_type=JobEventType.STATUS_CHANGE, data__status=Job.RUNNING)
            .order_by("created")
            .first()
        )
        return event.created if event else None

    def add_sub_status_event(  # pylint:  disable=too-many-positional-arguments
        self,
        job_id: uuid.UUID,
        origin: JobEventOrigin,
        context: JobEventContext,
        sub_status: str = None,
    ):
        """Sub Status change event for jobs."""

        logger.info(
            "[add_sub_status_event] job_id=%s | Set sub_status to %s | %s %s %s",
            job_id,
            sub_status,
            JobEventType.SUB_STATUS_CHANGE,
            origin,
            context,
        )

        return self.create(
            job_id=job_id,
            origin=origin,
            context=context,
            event_type=JobEventType.SUB_STATUS_CHANGE,
            data={"sub_status": sub_status},
        )

    def add_error_event(  # pylint:  disable=too-many-positional-arguments
        self,
        job_id: uuid.UUID,
        origin: JobEventOrigin,
        context: JobEventContext,
        code: str,
        message: str,
        exception: str,
        args: Any,
    ):
        """
        Creates an error event for jobs.

        Args:
            job_id (str): Unique identifier of the job.
            origin (JobEventOrigin): The creation major context (API, SCHEDULER...),
            context (JobEventContext): The creation minor context such as an specific endpoint or method,
            code (str): The error code to uniquely identify the reason,
            message (str): A human readable reason for the error,
            args (Any): Additional information that can be useful to understand the error,
        """

        return self.create(
            job_id=job_id,
            origin=origin,
            context=context,
            event_type=JobEventType.ERROR,
            data={"code": code, "message": message, "exception": exception, "args": args},
        )

    def get_job_events(  # pylint:  disable=too-many-positional-arguments
        self,
        job_id: uuid.UUID,
        event_type: str | None,
    ):
        """
        Get all events of the type `event_type` for jobs.

        Args:
            job_id (str): Unique identifier of the job.
            event_type (str): The event type to filter.
        """

        events = self.filter(
            job_id=job_id,
        )
        if event_type:
            events = events.filter(event_type=event_type)

        return events
