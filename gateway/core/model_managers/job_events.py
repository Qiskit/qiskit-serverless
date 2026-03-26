"""Job events model manager."""

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


class JobEventType(StrEnum):
    """Job events type enum."""

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
