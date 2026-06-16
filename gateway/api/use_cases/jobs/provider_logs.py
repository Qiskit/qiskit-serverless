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
from api.use_cases.jobs.get_logs_response import GetLogsResponse
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Job, Program
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
    ) -> GetLogsResponse:
        """Return the provider logs of a job if the user has access.

        Returns:
            GetLogsResponse with redirect_url set (Fleet, logs ready),
            GetLogsResponse() with both fields None (Fleet, no logs yet),
            or GetLogsResponse with raw_log set (Ray).
        """
        try:
            job = Job.objects.get(id=job_id)
        except ObjectDoesNotExist:
            raise JobNotFoundException(job_id)

        if not JobAccessPolicies.can_read_provider_logs(user, job, accessible_functions=accessible_functions):
            raise InvalidAccessException(f"You don't have access to job [{job_id}]")

        if job.program.runner == Program.FLEETS:
            logs_storage = get_logs_storage(job)
            url = logs_storage.get_private_logs_url()
            if url:
                logger.info(
                    "[jobs-provider-logs] user_id=%s job_id=%s | Redirecting to presigned URL",
                    user.id,
                    job_id,
                )
                return GetLogsResponse(redirect_url=url)
            return GetLogsResponse()

        # Ray path
        logs_storage = get_logs_storage(job)
        logs = logs_storage.get_private_logs()
        if logs:
            return GetLogsResponse(raw_log=logs)

        runner = get_runner(job)
        if runner.is_active():
            try:
                lines = runner.provider_logs()
            except RunnerError:
                logger.warning(
                    "[get-provider-logs] job_id=%s user_id=%s runner=%s | Failed to get provider logs",
                    job.id,
                    user.id,
                    job.program.runner,
                )
                return GetLogsResponse(raw_log=f"Logs not available for job [{job_id}] during execution.")

            if not lines.private_logs:
                return GetLogsResponse(raw_log="")

            logger.info(
                "[get-provider-logs] job_id=%s user_id=%s runner=%s | Got provider logs from runner",
                job.id,
                user.id,
                job.program.runner,
            )
            return GetLogsResponse(raw_log="\n".join(lines.private_logs) + "\n")

        return GetLogsResponse(raw_log=job.logs)
