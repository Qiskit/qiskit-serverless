import uuid
from typing import Optional

from django.db.models import QuerySet

from enum import StrEnum


class JobEventsContext(StrEnum):
    API_SET_SUB_STATUS = "API - SetJobSubStatus"
    API_STOP_JOB = "API - StopJob"
    SCHEDULER = "Scheduler"
    RUN_PROGRAM_SERIALIZER = "RunProgramSerializer"


class JobEventsType(StrEnum):
    STATUS_CHANGE = "Status change"


class JobEventsQuerySet(QuerySet):
    def add_status_event(
        self,
        job_id: uuid.UUID,
        context: str,
        status: str,
        sub_status: Optional[str] = None,
        additional_info: Optional[str] = None,
    ):
        return self.create(
            job_id=job_id,
            context=context,
            event_type=JobEventsType.STATUS_CHANGE,
            data={
                "status": status,
                "sub_status": sub_status,
                "additional_info": additional_info,
            },
        )
