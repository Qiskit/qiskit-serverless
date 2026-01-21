"""
Use case: retrieve job logs.
"""

from typing import NamedTuple, Optional

from api.domain.function import check_logs
from api.domain.function.filter_logs import (
    extract_public_logs,
    remove_prefix_tags_in_logs,
)
from api.models import Job
from api.ray import get_job_handler


class LogsResponse(NamedTuple):
    # logs with [PUBLIC] prefix
    user_logs: Optional[str]
    # non filtered logs
    full_logs: str


class GetComputeResourceLogsUseCase:
    """Use case for retrieving job logs."""

    def execute(self, job: Job) -> Optional[LogsResponse]:
        """Return the logs of a job in a running compute resource.
        Provider function:
          - full_logs: Raw logs with [PUBLIC] and [PRIVATE] prefixes and all the third party logs
          - user_logs: Log lines that have the [PUBLIC] prefix but removing the prefix.
        User functions:
          - full_logs: All the logs with the prefixes removed for cleaner result.
          - user_logs: None.

        Args:
            job (Job): The job executed in the compute resource.

        Returns:
            LogsResponse: A NamedTuple with the filtered user_logs and full_logs.
        """

        if job.compute_resource and job.compute_resource.active:
            job_handler = get_job_handler(job.compute_resource.host)
            logs = job_handler.logs(job.ray_job_id)
            logs = check_logs(logs, job)
            if job.program.provider:
                user_logs = extract_public_logs(logs)
                return LogsResponse(full_logs=logs, user_logs=user_logs)

            # The user functions only have one log.
            return LogsResponse(
                full_logs=remove_prefix_tags_in_logs(logs), user_logs=None
            )

        return None
