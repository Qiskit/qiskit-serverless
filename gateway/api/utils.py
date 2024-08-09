"""Utilities."""

import base64
from collections import OrderedDict
import inspect
import json
import logging
import re
import time
import uuid
from typing import Any, Optional, Tuple, Union, Callable, Dict, List

from cryptography.fernet import Fernet
from ray.dashboard.modules.job.common import JobStatus
from django.conf import settings

from api.models import Job

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
        except Exception:  # pylint: disable=broad-exception-caught
            logger.debug("%s Retrying...", error_message)

        time.sleep(interval)
    return result


def encrypt_string(string: str) -> str:
    """Encrypts string using symmetrical encryption.

    Args:
        string: string to be encrypted

    Returns:
        encrypter string
    """
    code_bytes = settings.SECRET_KEY.encode("utf-8")
    fernet = Fernet(base64.urlsafe_b64encode(code_bytes.ljust(32)[:32]))
    return fernet.encrypt(string.encode("utf-8")).decode("utf-8")


def decrypt_string(string: str) -> str:
    """Decrypts string symmetrically encrypted.

    Args:
        string: encrypted string

    Returns:
        decrypted string
    """
    code_bytes = settings.SECRET_KEY.encode("utf-8")
    fernet = Fernet(base64.urlsafe_b64encode(code_bytes.ljust(32)[:32]))
    return fernet.decrypt(string.encode("utf-8")).decode("utf-8")


def build_env_variables(token, job: Job, arguments: str) -> Dict[str, str]:
    """Builds env variables for job.

    Args:
        token: django request token decoded
        job: job
        arguments: program arguments

    Returns:
        env variables dict
    """
    extra = {}
    if settings.SETTINGS_AUTH_MECHANISM != "default":
        extra = {
            "QISKIT_IBM_TOKEN": str(token),
            "QISKIT_IBM_CHANNEL": settings.QISKIT_IBM_CHANNEL,
            "QISKIT_IBM_URL": settings.QISKIT_IBM_URL,
        }
    return {
        **{
            "ENV_JOB_GATEWAY_TOKEN": str(token),
            "ENV_JOB_GATEWAY_HOST": str(settings.SITE_HOST),
            "ENV_JOB_ID_GATEWAY": str(job.id),
            "ENV_JOB_ARGUMENTS": arguments,
        },
        **extra,
    }


def encrypt_env_vars(env_vars: Dict[str, str]) -> Dict[str, str]:
    """Encrypts tokens in env variables.

    Args:
        env_vars: env variables dict

    Returns:
        encrypted env vars dict
    """
    for key, value in env_vars.items():
        if "token" in key.lower():
            env_vars[key] = encrypt_string(value)
    return env_vars


def decrypt_env_vars(env_vars: Dict[str, str]) -> Dict[str, str]:
    """Decrypts tokens in env variables.

    Args:
        env_vars: env variables dict

    Returns:
        decrypted env vars dict
    """
    for key, value in env_vars.items():
        if "token" in key.lower():
            try:
                env_vars[key] = decrypt_string(value)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.error("Cannot decrypt %s.", key)
    return env_vars


def generate_cluster_name(username: str) -> str:
    """generate cluster name.

    Args:
        username: user name for the cluster

    Returns:
        generated cluster name
    """
    pattern = re.compile("[^a-zA-Z0-9-.]")
    cluster_name = f"c-{re.sub(pattern,'-',username)}-{str(uuid.uuid4())[:8]}"
    return cluster_name


def check_logs(logs: Union[str, None], job: Job) -> str:
    """Add error message to logs for faild jobs with empty logs.
    Args:
        logs: logs of the job
        job:  job model

    Returns:
        logs with error message and metadata.
    """
    if job.status == Job.FAILED and logs in ["", None]:
        logs = f"Job {job.id} failed due to an internal error."
        logger.warning("Job %s failed due to an internal error.", job.id)
    return logs


def safe_request(request: Callable) -> Optional[Dict[str, Any]]:
    """Makes safe request and parses json response."""
    result = None
    response = None
    try:
        response = request()
    except Exception:  # pylint: disable=broad-exception-caught
        logger.error("Exception sending request in safe_request")

    if response is not None and response.ok:
        try:
            result = json.loads(response.text)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.error("Response is not valid json in safe_request")
    if response is not None and not response.ok:
        logger.error("%d : %s", response.status_code, response.text)

    return result


def remove_duplicates_from_list(original_list: List[Any]) -> List[Any]:
    """Remove duplicates from a list maintining the order.
    Args:
        original_list: list with the original values

    Returns:
        a list without duplicates maintining the order
    """
    return list(OrderedDict.fromkeys(original_list))
