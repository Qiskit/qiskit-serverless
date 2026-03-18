"""
Use case for retrieving job events.
"""

from typing import List
from uuid import UUID

from django.contrib.auth.models import AbstractUser

from api.access_policies.jobs import JobAccessPolicies
from api.domain.exceptions.invalid_access_exception import InvalidAccessException
from api.domain.exceptions.job_not_found_exception import JobNotFoundException
from core.models import Job, JobEvent


class ListJobsEventsUseCase:
    """Use case for retrieving user jobs events."""

    def execute(self, job_id: UUID, user: AbstractUser, event_type: str) -> List[Job]:
        """
        Retrieve user jobs events

        Args:
            job_id (str): Unique identifier of the job.
            user (AbstractUser): The user attempting to retrieve the event.
            event_type (str): The event type to filter.

        Returns:
            list[Job]: (jobs, total_count)
        """
        job = Job.objects.get(id=job_id)
        if job is None:
            raise JobNotFoundException(str(job_id))

        if not JobAccessPolicies.can_read_events(user, job):
            raise InvalidAccessException(f"You don't have access to read events of the job [{job_id}]")

        queryset = JobEvent.objects.get_job_events(job_id, event_type)

        return list(queryset)
