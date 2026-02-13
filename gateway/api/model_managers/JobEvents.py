import uuid
from typing import Optional

from django.db.models import QuerySet


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
            data={
                "status": status,
                "sub_status": sub_status,
                "additional_info": additional_info,
            },
        )
