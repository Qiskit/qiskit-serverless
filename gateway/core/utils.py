# This code is a Qiskit project.
#
# (C) Copyright IBM 2024.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""
===========================================================
Utilities (:mod:`qiskit_serverless.utils.utils`)
===========================================================

.. currentmodule:: qiskit_serverless.utils.utils

Qiskit Serverless utilities
====================================

.. autosummary::
    :toctree: ../stubs/

    utility functions
"""

import base64
import json
import logging
import os
import re
import time
import uuid
from typing import Callable, Dict, List, Optional, Type, Union

from cryptography.fernet import Fernet
from django.conf import settings
from ray.dashboard.modules.job.common import JobStatus


def sanitize_file_path(path: str):
    """sanitize file path.
    Sanitization:
        character string '..' is replaced to '_'.
        character except '0-9a-zA-Z-_.' and directory delimiter('/' or '\')
            is replaced to '_'.

    Args:
        path: file path

    Returns:
        sanitized filepath
    """
    if ".." in path:
        path = path.replace("..", "_")
    pattern = "[^0-9a-zA-Z-_." + os.sep + "]+"
    return re.sub(pattern, "_", path)


logger = logging.getLogger("utils")


def retry_function(  # pylint:  disable=too-many-positional-arguments
    callback: Callable,
    num_retries: int = 10,
    interval: int = 1,
    exceptions: Optional[List[Type[Exception]]] = None,
    error_message: Optional[str] = None,
    error_message_level: int = logging.DEBUG,
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
    name = function_name or getattr(callback, "__name__", "<callback>")

    for attempt in range(1, num_retries + 1):
        try:
            return callback()
        except Exception as e:  # pylint: disable=broad-exception-caught
            if exceptions is not None and not isinstance(e, tuple(exceptions)):
                raise

            # If it's the last allowed attempt, propagate the original exception.
            if attempt == num_retries:
                raise

            # Log and wait before next attempt.
            logger.log(
                error_message_level,
                "[%s] attempt %d/%d failed%s%s",
                name,
                attempt,
                num_retries,
                ": " if error_message else "",
                error_message or str(e),
            )
            time.sleep(interval)

    return None


def encrypt_string(string: str) -> str:
    """Encrypts string using symmetrical encryption.

    Args:
        string: string to be encrypted

    Returns:
        encrypted string
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
    # Force capital letters to be lowercase
    lowercase_username = username.lower()[:20]

    # Substitute any not valid character by "-"
    pattern = re.compile("[^a-z0-9-]")
    cluster_name = (
        f"c-{re.sub(pattern, '-', lowercase_username)}-{str(uuid.uuid4())[:8]}"
    )
    return cluster_name


def ray_job_status_to_model_job_status(ray_job_status):
    """Maps ray job status to model job status."""
    # pylint: disable=import-outside-toplevel
    from core.models import Job  # Import here to avoid circular dependency

    mapping = {
        JobStatus.PENDING: Job.PENDING,
        JobStatus.RUNNING: Job.RUNNING,
        JobStatus.STOPPED: Job.STOPPED,
        JobStatus.SUCCEEDED: Job.SUCCEEDED,
        JobStatus.FAILED: Job.FAILED,
    }
    return mapping.get(ray_job_status, Job.FAILED)


def create_gpujob_allowlist():
    """
    Create dictionary of jobs allowed to run on gpu nodes.

    Sample format of json:
        { "gpu-functions": { "mockprovider": [ "my-first-pattern" ] } }
    """
    try:
        with open(settings.GATEWAY_GPU_JOBS_CONFIG, encoding="utf-8", mode="r") as f:
            gpujobs = json.load(f)
    except IOError as e:
        logger.error("Unable to open gpu job config file: %s", e)
        raise ValueError("Unable to open gpu job config file") from e
    except ValueError as e:
        logger.error("Unable to decode gpu job allowlist: %s", e)
        raise ValueError("Unable to decode gpujob allowlist") from e

    return gpujobs


def check_logs(logs: Union[str, None], job) -> str:
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
    # pylint: disable=import-outside-toplevel
    from core.models import Job  # Import here to avoid circular dependency

    if job.status == Job.FAILED and not logs:
        logs = f"Job {job.id} failed due to an internal error."
        logger.warning("Job %s failed due to an internal error.", job.id)
        print(f"Job {job.id} failed due to an internal error.")

        return logs

    if not logs:
        return ""

    max_bytes = settings.FUNCTIONS_LOGS_SIZE_LIMIT

    logs_size = len(logs)

    if logs_size > max_bytes:
        logger.warning(
            "Job %s is exceeding the maximum size for logs %s MB > %s MB.",
            job.id,
            logs_size,
            max_bytes,
        )

        # truncate logs discarding older
        logs = logs[-max_bytes:]

        logs = (
            "[Logs exceeded maximum allowed size ("
            + str(max_bytes / (1024**2))
            + " MB). Logs have been truncated, discarding the oldest entries first.]\n"
            + logs
        )

    return logs
