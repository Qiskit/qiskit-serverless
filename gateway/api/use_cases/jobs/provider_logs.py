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
from api.use_cases.jobs.logs_result import LogsResult
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
    ) -> LogsResult:
        """Return the provider logs of a job if the user has access.

        Returns:
            LogsResult with redirect_url set (Fleet, logs ready),
            LogsResult() with both fields None (Fleet, no logs yet),
            or LogsResult with raw_log set (Ray).
        """
        try:
            job = Job.objects.select_related("program__code_engine_project").get(id=job_id)
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
                return LogsResult(redirect_url=url)
            return LogsResult()

        # Ray path
        logs_storage = get_logs_storage(job)
        logs = logs_storage.get_private_logs()
        if logs:
            return LogsResult(raw_log=logs)

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
                return LogsResult(raw_log=f"Logs not available for job [{job_id}] during execution.")

            logger.info(
                "[get-provider-logs] job_id=%s user_id=%s runner=%s | Got provider logs from runner",
                job.id,
                user.id,
                job.program.runner,
            )
            logs = check_logs(logs, job)
            return LogsResult(raw_log=filter_logs_with_non_public_tags(logs))

        return LogsResult(raw_log=job.logs)
