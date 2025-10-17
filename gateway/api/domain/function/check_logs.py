"""This class contain methods to manage the logs in the application."""

import logging
import sys
from typing import Union

from django.conf import settings

from api.models import Job


logger = logging.getLogger("utils")


def check_logs(logs: Union[str, None], job: Job) -> str:
    """Add error message to logs for failed jobs with empty logs.
    Args:
        logs: logs of the job
        job:  job model

    Returns:
        logs with error message and metadata.
    """

    max_mb = int(settings.FUNCTIONS_LOGS_SIZE_LIMIT)
    max_bytes = max_mb * 1024**2

    if job.status == Job.FAILED and logs in ["", None]:
        logs = f"Job {job.id} failed due to an internal error."
        logger.warning("Job %s failed due to an internal error.", job.id)

        return logs

    logs_size = sys.getsizeof(logs)
    if logs_size == 0:
        return logs

    if logs_size > max_bytes:
        logger.warning(
            "Job %s is exceeding the maximum size for logs %s MB > %s MB.",
            job.id,
            logs_size,
            max_mb,
        )
        ratio = max_bytes / logs_size
        new_length = max(1, int(len(logs) * ratio))

        # truncate logs depending of the ratio
        logs = logs[:new_length]
        logs += (
            "\nLogs exceeded maximum allowed size ("
            + str(max_mb)
            + " MB) and could not be stored."
        )

    return logs
