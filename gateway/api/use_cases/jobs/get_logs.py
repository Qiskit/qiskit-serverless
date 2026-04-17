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
from core.domain.filter_logs import remove_prefix_tags_in_logs, filter_logs_with_public_tags
from core.models import Job
from core.services.runners import get_runner, RunnerError
from core.utils import check_logs
from core.services.storage.logs_storage import LogsStorage

logger = logging.getLogger("api.GetJobLogsUseCase")


class GetJobLogsUseCase:
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

        if not JobAccessPolicies.can_read_user_logs(user, job):
            raise InvalidAccessException(f"You don't have access to read user logs of the job [{job_id}]")

        # Logs stored in COS. They are already filtered
        logs_storage = LogsStorage(job)
        logs = logs_storage.get_public_logs()
        if logs:
            return logs

        runner = get_runner(job)
        if runner.is_active():
            try:
                logs = runner.logs()
            except RunnerError:
                return "Logs not available for this job during execution."

            logs = check_logs(logs, job)

            job_id_type = "ray_job_id" if job.ray_job_id else "fleet_id"
            logger.info("Getting logs from %s [%s] job_id=%s", job_id_type, job.ray_job_id or job.fleet_id, job.id)

            if job.program.provider:
                # Public logs from a provider job
                return filter_logs_with_public_tags(logs)

            # Public logs from a user job
            return remove_prefix_tags_in_logs(logs)

        # Legacy: Get from db.
        if job.program.provider:
            # Public logs from a provider job
            return "No logs available."

        # Public logs from a user job
        return job.logs
