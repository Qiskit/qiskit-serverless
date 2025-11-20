"""This class contain methods to manage the logs in the application."""

import logging
from typing import Union

from django.conf import settings

from api.models import Job


logger = logging.getLogger("utils")


def check_logs(logs: Union[str, None], job: Job) -> str:
    """
    This method verifies the integrity of logs to be able
    to save them:
        - We write a feedback for Failed jobs without logs
        - Limited to max_mb the logs from a Function

    Args:
        logs: logs of the job
        job:  job model

    Returns:
        logs with error message and metadata.
    """

    if job.status == Job.FAILED and not logs:
        logs = f"Job {job.id} failed due to an internal error."
        logger.warning("Job %s failed due to an internal error.", job.id)

        return logs

    if not logs:
        return ""

    max_mb = int(settings.FUNCTIONS_LOGS_SIZE_LIMIT)
    max_bytes = max_mb * 1024**2

    logs_size = len(logs)

    if logs_size > max_bytes:
        logger.warning(
            "Job %s is exceeding the maximum size for logs %s MB > %s MB.",
            job.id,
            logs_size,
            max_mb,
        )

        # truncate logs discarding older
        logs = logs[-max_bytes:]

        logs = (
            "[Logs exceeded maximum allowed size ("
            + str(max_mb)
            + " MB). Older logs are discarded.]\n"
            + logs
        )

    return logs
