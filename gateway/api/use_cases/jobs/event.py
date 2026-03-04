"""
Use case for saving job results.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID
import logging
from django.contrib.auth.models import AbstractUser
from api.repositories.jobs import JobsRepository
from api.domain.exceptions.job_not_found_exception import JobNotFoundException
from api.access_policies.jobs import JobAccessPolicies
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from core.services.storage.result_storage import ResultStorage
from core.models import Job, JobEvent

logger = logging.getLogger("gateway.use_cases.jobs")


@dataclass(slots=True)
class EventData:
    """
    Create event data.
    """

    event_type: str
    code: str
    message: str
    args: Any


class JobEventUseCase:
    """
    Use case for creating an event for a Job.
    """

    jobs_repository = JobsRepository()

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
        job = self.jobs_repository.get_job_by_id(job_id)
        if job is None:
            raise JobNotFoundException(job_id)

        can_create_events = JobAccessPolicies.can_create_events(user, job)
        if not can_create_events:
            raise JobNotFoundException(job_id)

        JobEvent.objects.add_error_event(
            job_id, JobEventOrigin.API, JobEventContext.SEND_ERROR, data.event_type, data.code, data.message, data.args
        )
