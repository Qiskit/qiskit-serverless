"""
Use case: retrieve job logs.
"""

import logging
from typing import Final
from uuid import UUID

from django.contrib.auth.models import AbstractUser

from api.access_policies.jobs import JobAccessPolicies
from api.domain.exceptions.job_not_found_exception import JobNotFoundException
from api.domain.exceptions.invalid_access_exception import InvalidAccessException
from api.domain.function.filter_logs import filter_logs_with_non_public_tags
from core.utils import check_logs
from core.services.ray import get_job_handler
from api.repositories.jobs import JobsRepository
from core.services.storage.logs_storage import LogsStorage

logger = logging.getLogger("gateway")


class GetProviderJobLogsUseCase:
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
            raise JobNotFoundException(job_id)

        if not JobAccessPolicies.can_read_provider_logs(user, job):
            raise InvalidAccessException(f"You don't have access to job [{job_id}]")

        # Logs stored in COS. They are already filtered
        logs_storage = LogsStorage(job)
        logs = logs_storage.get_private_logs()
        if logs:
            return logs

        # Get from Ray if it is already running. Then filter
        if job.compute_resource and job.compute_resource.active:
            try:
                job_handler = get_job_handler(job.compute_resource.host)
            except ConnectionError:
                return "Logs not available for this job during execution."

            logs = job_handler.logs(job.ray_job_id)
            logger.info("Getting provider logs from ray job [%s]", job.ray_job_id)

            logs = check_logs(logs, job)
            return filter_logs_with_non_public_tags(logs)

        # Legacy: Get from db.
        return job.logs
