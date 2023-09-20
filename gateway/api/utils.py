"""Utilities."""
import base64
import inspect
import json
import logging
import time
from typing import Optional, Tuple, Callable, Dict

from cryptography.fernet import Fernet
from ray.dashboard.modules.job.common import JobStatus
from django.conf import settings

from .models import Job, Program

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


def build_env_variables(request, job: Job, program: Program) -> Dict[str, str]:
    """Builds env variables for job.

    Args:
        request: django request
        job: job
        program: program

    Returns:
        env variables dict
    """
    extra = {}
    if settings.SETTINGS_AUTH_MECHANISM != "default":
        extra = {
            "QISKIT_IBM_TOKEN": str(request.auth.token.decode()),
            "QISKIT_IBM_CHANNEL": settings.QISKIT_IBM_CHANNEL,
            "QISKIT_IBM_URL": settings.QISKIT_IBM_URL,
        }
    return {
        **{
            "ENV_JOB_GATEWAY_TOKEN": str(request.auth.token.decode()),
            "ENV_JOB_GATEWAY_HOST": str(settings.SITE_HOST),
            "ENV_JOB_ID_GATEWAY": str(job.id),
            "ENV_JOB_ARGUMENTS": program.arguments,
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
            except (
                Exception  # pylint: disable=broad-exception-caught
            ) as decryption_error:
                logger.error("Cannot decrypt %s. %s", key, decryption_error)
    return env_vars
