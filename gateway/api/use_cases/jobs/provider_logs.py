"""
Use case: retrieve job logs.
"""

import logging
from typing import Optional
from uuid import UUID

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ObjectDoesNotExist

from api.access_policies.jobs import JobAccessPolicies
from api.domain.exceptions.job_not_found_exception import JobNotFoundException
from api.domain.exceptions.invalid_access_exception import InvalidAccessException
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.domain.filter_logs import filter_logs_with_non_public_tags
from core.models import Job, Program
from core.utils import check_logs
from core.services.runners import get_runner, RunnerError
from core.services.storage import get_logs_storage

logger = logging.getLogger("api.GetProviderJobLogsUseCase")


class GetProviderJobLogsUseCase:
    """Use case for retrieving job logs."""

    def execute(
        self,
        job_id: UUID,
        user: AbstractUser,
        accessible_functions: Optional[FunctionAccessResult] = None,
    ) -> str:
        """Return the logs of a job if the user has access.

        Args:
            job_id (str): Unique identifier of the job.
            user (AbstractUser): User requesting the logs.
            accessible_functions: Result from FunctionAccessClient; if None or
                use_legacy_authorization=True, falls back to Django groups.

        Raises:
            NotFoundError: If the job does not exist.

        Returns:
            str: Job logs if accessible, otherwise a message indicating no logs are available.
        """
        try:
            job = Job.objects.get(id=job_id)
        except ObjectDoesNotExist:
            raise JobNotFoundException(job_id)

        if not JobAccessPolicies.can_read_provider_logs(user, job, accessible_functions=accessible_functions):
            raise InvalidAccessException(f"You don't have access to job [{job_id}]")

        # Logs stored in COS. They are already filtered
        logs_storage = get_logs_storage(job)
        logs = logs_storage.get_private_logs()
        if logs:
            return logs

        if job.program.runner == Program.FLEETS:
            # Fleets wrapper needs up to 15 seconds to start uploading a log to COS
            return "No logs yet."

        # Ray only path
        runner = get_runner(job)
        if runner.is_active():
            try:
                logs = runner.provider_logs()
            except RunnerError:
                logger.warning(
                    "[get-provider-logs] job_id=%s user_id=%s runner=%s | Failed to get provider logs",
                    job.id,
                    user.id,
                    job.program.runner,
                )
                return f"Logs not available for job [{job_id}] during execution."

            logger.info(
                "[get-provider-logs] job_id=%s user_id=%s runner=%s | Got provider logs from runner",
                job.id,
                user.id,
                job.program.runner,
            )
            logs = check_logs(logs, job)
            return filter_logs_with_non_public_tags(logs)

        # Legacy: Get from db.
        return job.logs
