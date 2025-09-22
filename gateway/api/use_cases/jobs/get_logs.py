"""
Use case: retrieve job logs.
"""
from typing import Final
from uuid import UUID

from django.contrib.auth.models import AbstractUser

from api.domain.exceptions.not_found_error import NotFoundError
from api.domain.exceptions.forbidden_error import ForbiddenError
from api.repositories.jobs import JobsRepository
from api.access_policies.providers import ProviderAccessPolicy
from api.access_policies.jobs import JobAccessPolicies


NO_LOGS_MSG: Final[str] = "No available logs"


class GetJobLogsUseCase:
    """Use case for retrieving job logs."""

    jobs_repository = JobsRepository()

    def execute(self, job_id: UUID, user: AbstractUser) -> str:
        """Return the logs of a job if the user has access.

        Args:
            job_id (str): Unique identifier of the job.
            user (AbstractUser): User requesting the logs.

        Raises:
            NotFoundError: If the job does not exist.

        Returns:
            str: Job logs if accessible, otherwise a message indicating no logs are available.
        """
        job = self.jobs_repository.get_job_by_id(job_id)
        if job is None:
            raise NotFoundError(f"Job [{job_id}] not found")

        # Case 1: Provider function - check provider access policy
        if not JobAccessPolicies.can_read_logs(user, job):
            raise ForbiddenError(f"You don't have access to job [{job_id}]")

        return job.logs
