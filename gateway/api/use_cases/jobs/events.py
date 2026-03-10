"""This module contains the usecase get_jos"""

from typing import List
from uuid import UUID

from django.contrib.auth.models import AbstractUser

from api.access_policies.jobs import JobAccessPolicies
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.domain.exceptions.invalid_access_exception import InvalidAccessException
from api.domain.exceptions.job_not_found_exception import JobNotFoundException
from core.models import Job, JobEvent
from api.repositories.functions import FunctionRepository
from api.repositories.jobs import JobFilters, JobsRepository


class JobsEventsUseCase:
    """Use case for retrieving user jobs with optional filtering and pagination."""

    function_repository = FunctionRepository()
    jobs_repository = JobsRepository()

    def execute(self, job_id: UUID, user: AbstractUser, event_type: str) -> tuple[List[Job], int]:
        """
        Retrieve user jobs with optional filters and pagination.

        Returns:
            tuple[list[Job], int]: (jobs, total_count)
        """
        job = self.jobs_repository.get_job_by_id(job_id)
        if job is None:
            raise JobNotFoundException(str(job_id))

        if not JobAccessPolicies.can_read_events(user, job):
            raise InvalidAccessException(f"You don't have access to read user logs of the job [{job_id}]")

        queryset = JobEvent.objects.get_job_events(job_id, event_type)

        return list(queryset)
