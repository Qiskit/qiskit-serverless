"""
Use case for creating job events.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID
import logging
from django.contrib.auth.models import AbstractUser
from api.domain.exceptions.invalid_access_exception import InvalidAccessException
from api.domain.exceptions.job_not_found_exception import JobNotFoundException
from api.access_policies.jobs import JobAccessPolicies
from core.model_managers.job_events import JobEventContext, JobEventOrigin, JobEventType
from core.services.job_status import update_job_status
from core.models import Job, JobEvent

logger = logging.getLogger("gateway.use_cases.jobs")


@dataclass(slots=True)
class EventData:
    """
    Create event data.
    """

    event_type: str
    error_type: str
    code: str
    message: str
    args: Any


class CreateJobEventUseCase:
    """
    Use case for creating an event for a Job.
    """

    def execute(self, job_id: UUID, user: AbstractUser, data: EventData) -> Job:
        """Creates an event for a given job.

        Args:
            job_id (str): Unique identifier of the job.
            user (AbstractUser): The user attempting to create the event.
            data (EventData): The event data.

        Raises:
            NotFoundError: If the job does not exist or the user is not allowed to save results.

        Returns:
            Job: The updated job object with the stored result.
        """
        job = Job.objects.get(id=job_id)
        if job is None:
            raise JobNotFoundException(job_id)

        can_create_events = JobAccessPolicies.can_create_events(user, job)
        if not can_create_events:
            raise JobNotFoundException(job_id)

        update_job_status(job)

        if job.status != Job.RUNNING:
            raise InvalidAccessException("You can create events on RUNNING jobs only")

        if data.event_type == JobEventType.ERROR:
            JobEvent.objects.add_error_event(
                job_id,
                JobEventOrigin.API,
                JobEventContext.SEND_ERROR,
                data.code,
                data.message,
                data.error_type,
                data.args,
            )
