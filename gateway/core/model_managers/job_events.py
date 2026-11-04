"""Job events model manager."""

import logging
from datetime import datetime
from typing import Any, Self
import uuid

from enum import StrEnum

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

    # Gateway: job status STOPPED, or STOPPING for a Fleets job
    STOP_JOB = "STOP_JOB"

    # Scheduler: PENDING to RUNNING, RUNNING to FAILED/STOPPED/SUCCEEDED/STOPPING, and STOPPING to any terminal
    UPDATE_JOB_STATUS = "UPDATE_JOB_STATUS"

    # Gateway: status RUNNING, substatus change
    SET_SUB_STATUS = "SET_SUB_STATUS"

    # Admin: any state to any state
    SAVE_MODEL = "SAVE_MODEL"
    SEND_ERROR = "SEND_ERROR"

    # Scheduler: a filler job was created and submitted to Fleets (status PENDING or FAILED)
    FILLER_SUBMIT = "FILLER_SUBMIT"

    # Scheduler: a filler job was stopped to free capacity (status STOPPING or STOPPED)
    FILLER_STOP = "FILLER_STOP"

    FILLER_FAILED = "FILLER_FAILED"

    # Scheduler: a PENDING or RUNNING job of a blocked resource was stopped (status STOPPING or STOPPED)
    BLOCKED_RESOURCE_STOP = "BLOCKED_RESOURCE_STOP"


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
        event_time: datetime | None = None,
    ):
        """Status change event for jobs. event_time is when the status was really reached, if the runner knows."""

        logger.info(
            "[add_status_event] job_id=%s | Set status to %s | %s %s %s",
            job_id,
            status,
            JobEventType.STATUS_CHANGE,
            origin,
            context,
        )

        return self.create(
            job_id=job_id,
            origin=origin,
            context=context,
            event_type=JobEventType.STATUS_CHANGE,
            event_time=event_time,
            data={"status": status},
        )

    def running_status_events(self) -> Self:
        """The status changes to RUNNING, oldest first. The first one is when the job started."""
        from core.models import Job  # pylint: disable=import-outside-toplevel, cyclic-import

        return self.filter(event_type=JobEventType.STATUS_CHANGE, data__status=Job.RUNNING).order_by("created")

    def terminal_status_events(self) -> Self:
        """The status changes to a terminal status, oldest first. The first one is when the job ended."""
        from core.models import Job  # pylint: disable=import-outside-toplevel, cyclic-import

        return self.filter(event_type=JobEventType.STATUS_CHANGE, data__status__in=Job.TERMINAL_STATUSES).order_by(
            "created"
        )

    def first_running_at(self, job_id: uuid.UUID):
        """When this job first reached RUNNING: the time the runner gave, or else when the event was written.
        Returns None if it never did (still queued/pending, or terminated without running).
        """
        return self._time_of(self.filter(job_id=job_id).running_status_events().first())

    def first_terminal_at(self, job_id: uuid.UUID):
        """When this job first reached a terminal status: the time the runner gave, or else when the event was
        written. Returns None if it never did.
        """
        return self._time_of(self.filter(job_id=job_id).terminal_status_events().first())

    @staticmethod
    def _time_of(event):
        """The time the runner gave for the event, or else when it was written. None without an event."""
        if event is None:
            return None
        return event.event_time or event.created

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
