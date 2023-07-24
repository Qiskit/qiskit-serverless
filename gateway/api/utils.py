"""Utilities."""
import inspect
import json
import logging
import time
from typing import Optional, Tuple, Callable
from ray.dashboard.modules.job.common import JobStatus

from .models import Job

logger = logging.getLogger("commands")


def try_json_loads(data: str) -> Tuple[bool, Optional[dict]]:
    """Dumb check if data is json :)"""
    try:
        json_object = json.loads(data)
    except ValueError:
        return False, None
    return True, json_object


def ray_job_status_to_model_job_status(ray_job_status):
    """Maps ray job status to model job status."""

    mapping = {
        JobStatus.PENDING: Job.PENDING,
        JobStatus.RUNNING: Job.RUNNING,
        JobStatus.STOPPED: Job.STOPPED,
        JobStatus.SUCCEEDED: Job.SUCCEEDED,
        JobStatus.FAILED: Job.FAILED,
    }
    return mapping.get(ray_job_status, Job.FAILED)


def retry_function(
    callback: Callable,
    num_retries: int = 10,
    interval: int = 1,
    error_message: Optional[str] = None,
    function_name: Optional[str] = None,
):
    """Retries to call callback function.

    Args:
        callback: function
        num_retries: number of tries
        interval: interval between tries
        error_message: error message
        function_name: name of executable function

    Returns:
        function result of None
    """
    success = False
    run = 0
    result = None
    name = function_name or inspect.stack()[1].function

    while run < num_retries and not success:
        run += 1

        logger.debug("[%s] attempt %d", name, run)

        try:
            result = callback()
            success = True
        except Exception as error:  # pylint: disable=broad-exception-caught
            logger.debug("%s Retrying...:\nDetails: %s", error_message, error)

        time.sleep(interval)
    return result
