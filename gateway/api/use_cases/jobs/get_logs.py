"""
Use case: retrieve job logs.
"""

from typing import Final
from uuid import UUID

from django.contrib.auth.models import AbstractUser

from api.access_policies.jobs import JobAccessPolicies
from api.domain.exceptions.not_found_error import NotFoundError
from api.domain.exceptions.forbidden_error import ForbiddenError
from api.domain.function import check_logs
from api.domain.function.filter_logs import extract_public_logs
from api.ray import get_job_handler
from api.repositories.jobs import JobsRepository
from api.services.storage.enums.working_dir import WorkingDir
from api.services.storage.logs_storage import LogsStorage


NO_LOGS_MSG: Final[str] = "No available logs"
NO_LOGS_MSG_2: Final[str] = "No logs yet."


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

        if not JobAccessPolicies.can_read_logs(user, job):
            raise ForbiddenError(f"You don't have access to job [{job_id}]")

        logs_storage = LogsStorage(
            username=user.username,
            working_dir=WorkingDir.USER_STORAGE,
            function_title=job.program.title,
            provider_name=job.program.provider.name if job.program.provider else None,
        )

        logs = logs_storage.get(job_id)

        # Logs stored in storage.
        if logs:
            return logs

        # Get from Ray if it is already running.
        if job.compute_resource and job.compute_resource.active:
            job_handler = get_job_handler(job.compute_resource.host)
            logs = job_handler.logs(job.ray_job_id)
            logs = check_logs(logs, job)
            logs = extract_public_logs(logs)
            return logs

        # Legacy: Get from db.
        logs = job.logs

        return logs
