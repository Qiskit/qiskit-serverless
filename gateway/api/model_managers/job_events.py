"""Job events model manager."""

import uuid
from typing import Optional

from enum import StrEnum

from django.db.models import QuerySet


class JobEventOrigin(StrEnum):
    """Job events origin enum."""

    API = "API"
    SCHEDULER = "SCHEDULER"


class JobEventContext(StrEnum):
    """Job events context enum."""

    SET_SUB_STATUS = "SET_SUB_STATUS"
    STOP_JOB = "STOP_JOB"
    RUN_PROGRAM_SERIALIZER = "RUN_PROGRAM_SERIALIZER"
    UPDATE_JOB_STATUS = "UPDATE_JOB_STATUS"
    SCHEDULE_JOBS = "SCHEDULE_JOBS"


class JobEventType(StrEnum):
    """Job events type enum."""

    STATUS_CHANGE = "STATUS_CHANGE"


class JobEventQuerySet(QuerySet):
    """Job events query set to transform into a manager."""

    def add_status_event(  # pylint:  disable=too-many-positional-arguments
        self,
        job_id: uuid.UUID,
        origin: JobEventOrigin,
        context: JobEventContext,
        status: str,
        sub_status: Optional[str] = None,
        additional_info: Optional[str] = None,
    ):
        """Status change event for jobs."""

        return self.create(
            job_id=job_id,
            origin=origin,
            context=context,
            event_type=JobEventType.STATUS_CHANGE,
            data={
                "status": status,
                "sub_status": sub_status,
                "additional_info": additional_info,
            },
        )
