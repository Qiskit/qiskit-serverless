"""Job events model manager."""

from typing import Any
import uuid

from enum import StrEnum

from django.db.models import QuerySet


class JobEventOrigin(StrEnum):
    """Job events origin enum."""

    API = "API"
    SCHEDULER = "SCHEDULER"
    BACKOFFICE = "BACKOFFICE"


class JobEventContext(StrEnum):
    """Job events context enum."""

    SET_SUB_STATUS = "SET_SUB_STATUS"
    STOP_JOB = "STOP_JOB"
    RUN_PROGRAM = "RUN_PROGRAM"
    UPDATE_JOB_STATUS = "UPDATE_JOB_STATUS"
    SCHEDULE_JOBS = "SCHEDULE_JOBS"
    SAVE_MODEL = "SAVE_MODEL"
    SEND_ERROR = "SEND_ERROR"


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
        """Status change event for jobs."""

        return self.create(
            job_id=job_id,
            origin=origin,
            context=context,
            event_type=JobEventType.STATUS_CHANGE,
            data={"status": status},
        )

    def add_sub_status_event(  # pylint:  disable=too-many-positional-arguments
        self,
        job_id: uuid.UUID,
        origin: JobEventOrigin,
        context: JobEventContext,
        sub_status: str = None,
    ):
        """Sub Status change event for jobs."""

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
        event_type: str,
        code: str,
        message: str,
        args: Any,
    ):
        """Sub Status change event for jobs."""

        return self.create(
            job_id=job_id,
            origin=origin,
            context=context,
            event_type=event_type,
            data={"code": code, "message": message, "args": args},
        )

    def get_job_events(  # pylint:  disable=too-many-positional-arguments
        self,
        job_id: uuid.UUID,
        event_type: str | None,
    ):
        """Sub Status change event for jobs."""

        events = self.filter(
            job_id=job_id,
        )
        if event_type:
            events.filter(event_type=event_type)

        return events
