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
from api.use_cases.jobs.logs_result import LogsResult
from core.domain.filter_logs import remove_prefix_tags_in_logs, filter_logs_with_public_tags
from core.models import Job, Program
from core.services.runners import get_runner, RunnerError
from core.utils import check_logs
from core.services.storage import get_logs_storage

logger = logging.getLogger("api.GetJobLogsUseCase")


class GetJobLogsUseCase:
    """Use case for retrieving job logs."""

    def execute(self, job_id: UUID, user: AbstractUser) -> LogsResult:
        """Return the logs of a job if the user has access.

        Returns:
            LogsResult with redirect_url set (Fleet, logs ready),
            LogsResult() with both fields None (Fleet, no logs yet),
            or LogsResult with raw_log set (Ray).
        """
        try:
            job = Job.objects.get(id=job_id)
        except ObjectDoesNotExist:
            raise JobNotFoundException(job_id)

        if not JobAccessPolicies.can_read_user_logs(user, job):
            raise InvalidAccessException(f"You don't have access to read user logs of the job [{job_id}]")

        # Logs stored in COS. They are already filtered
        logs_storage = get_logs_storage(job)

        if job.program.runner == Program.FLEETS:
            logs_storage = get_logs_storage(job)
            url = logs_storage.get_public_logs_url()
            if url:
                logger.info("[jobs-logs] user_id=%s job_id=%s | Redirecting to presigned URL", user.id, job_id)
                return LogsResult(redirect_url=url)
            return LogsResult()

        # Ray path: try COS storage first, then active runner, then DB legacy
        logs = logs_storage.get_public_logs()
        if logs:
            return LogsResult(raw_log=logs)

        runner = get_runner(job)
        if runner.is_active():
            try:
                logs = runner.logs()
            except RunnerError:
                return LogsResult(raw_log="Logs not available for this job during execution.")

            logs = check_logs(logs, job)
            logger.info("Getting logs from runner=%s job_id=%s", job.program.runner, job.id)

            if job.program.provider:
                return LogsResult(raw_log=filter_logs_with_public_tags(logs))
            return LogsResult(raw_log=remove_prefix_tags_in_logs(logs))

        if job.program.provider:
            return LogsResult(raw_log="No logs available.")
        return LogsResult(raw_log=job.logs)
