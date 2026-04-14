"""
Use case: retrieve job logs.
"""

import logging
from uuid import UUID

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ObjectDoesNotExist

from api.access_policies.jobs import JobAccessPolicies
from api.domain.exceptions.job_not_found_exception import JobNotFoundException
from api.domain.exceptions.invalid_access_exception import InvalidAccessException
from core.domain.filter_logs import filter_logs_with_non_public_tags
from core.models import Job
from core.utils import check_logs
from core.services.runners import get_runner, RunnerError
from core.services.storage.logs_storage import LogsStorage

logger = logging.getLogger("api.GetProviderJobLogsUseCase")


class GetProviderJobLogsUseCase:
    """Use case for retrieving job logs."""

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
        try:
            job = Job.objects.get(id=job_id)
        except ObjectDoesNotExist:
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
                logs = get_runner(job).logs()
            except RunnerError:
                return "Logs not available for this job during execution."

            logger.info(
                "[get-provider-logs] job_id=%s user_id=%s ray_job_id=%s | Getting provider logs from ray",
                job.id,
                user.id,
                job.ray_job_id,
            )

            logs = check_logs(logs, job)
            return filter_logs_with_non_public_tags(logs)

        # Legacy: Get from db.
        return job.logs
