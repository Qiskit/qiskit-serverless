"""
Use case for creating job events.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID
import logging
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth.models import AbstractUser
from api.domain.exceptions.invalid_access_exception import InvalidAccessException
from api.domain.exceptions.job_not_found_exception import JobNotFoundException
from api.access_policies.jobs import JobAccessPolicies
from core.model_managers.job_events import JobEventContext, JobEventOrigin, JobEventType
from core.models import Job, JobEvent

logger = logging.getLogger("gateway.use_cases.jobs")


@dataclass(slots=True)
class EventData:
    """
    Create event data.
    """

    event_type: str
    exception: str
    code: str
    message: str
    args: Any


class CreateJobEventUseCase:
    """
    Use case for creating an event for a Job.
    """

    def execute(self, job_id: UUID, user: AbstractUser, data: EventData) -> None:
        """Creates an event for a given job.

        Args:
            job_id (str): Unique identifier of the job.
            user (AbstractUser): The user attempting to create the event.
            data (EventData): The event data.

        Raises:
            JobNotFoundException: If the job does not exist or the user is not allowed to create events.
            InvalidAccessException: If the job is not in RUNNING status.
        """
        try:
            job = Job.objects.get(id=job_id)
        except ObjectDoesNotExist:
            raise JobNotFoundException(str(job_id))

        can_create_events = JobAccessPolicies.can_create_events(user, job)
        if not can_create_events:
            raise JobNotFoundException(str(job_id))

        # add events in PENDING and RUNNING is allowed
        # so we accept that we might have events before RUNNING

        if job.status not in Job.RUNNING_STATUSES:
            raise InvalidAccessException("You can create events on PENDING/RUNNING jobs only")

        if data.event_type == JobEventType.ERROR:
            # for now we only allow saving ERROR type events
            JobEvent.objects.add_error_event(
                job_id,
                JobEventOrigin.API,
                JobEventContext.SEND_ERROR,
                data.code,
                data.message,
                data.exception,
                data.args,
            )
