"""
Use case: retrieve job logs.
"""
from typing import Final
from uuid import UUID

from django.contrib.auth.models import AbstractUser

from api.access_policies.jobs import JobAccessPolicies
from api.domain.exceptions.not_found_error import NotFoundError
from api.domain.exceptions.forbidden_error import ForbiddenError
from api.models import Job
from api.repositories.jobs import JobsRepository
from api.access_policies.providers import ProviderAccessPolicy
from api.services.storage.enums.working_dir import WorkingDir
from api.services.storage.logs_storage import LogsStorage


NO_LOGS_MSG: Final[str] = "No available logs"
NO_LOGS_MSG_2: Final[str] = "No logs yet."


class PutProviderJobLogsUseCase:
    """Use case for writing job logs."""

    jobs_repository = JobsRepository()

    def execute(self, job_id: UUID, user: AbstractUser, log: str) -> None:
        """Return the logs of a job if the user has access.

        Args:
            job_id (str): Unique identifier of the job.
            user (AbstractUser): User requesting the logs.

        Raises:
            NotFoundError: If the job does not exist.

        Returns:
            None
        """
        job = self.jobs_repository.get_job_by_id(job_id)
        if job is None:
            raise NotFoundError(f"Job [{job_id}] not found")

        if job.status != Job.RUNNING:
            raise ForbiddenError(f"The job is not in running state.")

        if not job.program.provider or not ProviderAccessPolicy.can_access(
            user, job.program.provider
        ):
            raise ForbiddenError(f"You don't have access to job provider [{job_id}]")

        if not JobAccessPolicies.can_write_logs(user, job):
            raise ForbiddenError(f"You don't have access to job [{job_id}]")

        logs_storage = LogsStorage(
            username=user.username,
            working_dir=WorkingDir.PROVIDER_STORAGE,
            function_title=job.program.title,
            provider_name=job.program.provider.name,
        )

        logs_storage.put(job, log)
