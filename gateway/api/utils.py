"""Utilities."""

import base64
from collections import OrderedDict
import json
import logging
import re
import time
import uuid
from typing import Any, Optional, Tuple, Type, Callable, Dict, List
from django.conf import settings
from packaging.requirements import Requirement

from cryptography.fernet import Fernet
from ray.dashboard.modules.job.common import JobStatus
import objsize

from api.domain.authentication.channel import Channel

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


def build_env_variables(  # pylint: disable=too-many-positional-arguments
    channel: Channel,
    token: str,
    job: Job,
    trial_mode: bool,
    args: str = None,
    instance: Optional[str] = None,
) -> Dict[str, str]:
    """Builds env variables for job.

    Args:
        channel: Channel the user uses to authenticate
        token: django request token decoded
        job: job data to be executed
        trial_mode: identifies if the user is trial or not
        args: job arguments
        instance: IBM Cloud crn

    Returns:
        env variables dict
    """
    extra = {}
    # only set arguments envvar if not too big
    # remove this after sufficient time for users to upgrade client
    arguments = "{}"
    if args:
        if objsize.get_deep_size(args) < 100000:
            logger.debug("passing arguments as env_var for job [%s]", job.id)
            arguments = args
        else:
            logger.warning(
                "arguments for job [%s] are too large and will not be written to env_var",
                job.id,
            )

    if settings.SETTINGS_AUTH_MECHANISM != "default":
        if instance:
            extra = {
                "QISKIT_IBM_INSTANCE": str(instance),
            }
        # pylint: disable=fixme
        # TODO: remove this path once iqp classic is sunset for all users
        if channel.value == Channel.IBM_QUANTUM.value:
            url = "https://auth.quantum.ibm.com/api"
        else:
            url = settings.QISKIT_IBM_URL
        extra.update(
            {
                "QISKIT_IBM_TOKEN": str(token),
                "QISKIT_IBM_CHANNEL": channel.value,
                "QISKIT_IBM_URL": url,
            }
        )

    if instance:
        extra.update(
            {
                "ENV_JOB_GATEWAY_INSTANCE": str(instance),
            }
        )

    return {
        **{
            "ENV_JOB_GATEWAY_TOKEN": str(token),
            "ENV_JOB_GATEWAY_HOST": str(settings.SITE_HOST),
            "ENV_JOB_ID_GATEWAY": str(job.id),
            "ENV_JOB_ARGUMENTS": arguments,
            "ENV_ACCESS_TRIAL": str(trial_mode),
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
    # Force capital letters to be lowercase
    lowercase_username = username.lower()

    # Substitute any not valid character by "-"
    pattern = re.compile("[^a-z0-9-]")
    cluster_name = (
        f"c-{re.sub(pattern, '-', lowercase_username)}-{str(uuid.uuid4())[:8]}"
    )
    return cluster_name


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
    """Remove duplicates from a list maintaining the order.
    Args:
        original_list: list with the original values

    Returns:
        a list without duplicates maintaining the order
    """
    return list(OrderedDict.fromkeys(original_list))


def sanitize_name(name: Optional[str]):
    """Sanitize name"""
    if not name:
        return name
    # Remove all characters except alphanumeric, _, -, /
    return re.sub("[^a-zA-Z0-9_\\-/]", "", name)


def sanitize_boolean(value: Optional[str]) -> Optional[bool]:
    """Sanitize a string into a boolean."""
    if value is None:
        return None

    value = value.strip().lower()

    if value == "true":
        return True
    if value == "false":
        return False

    return None


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


def sanitize_file_name(name: Optional[str]):
    """Sanitize the name of a file"""
    if not name:
        return name
    # Remove all characters except alphanumeric, _, ., -
    return re.sub("[^a-zA-Z0-9_\\.\\-]", "", name)


def create_dynamic_dependencies_whitelist() -> Dict[str, Requirement]:
    """
    Create dictionary of allowed additional dependences for function providers.

    The format of the readed file should be a requirements.txt file.
    """
    try:
        with open(
            settings.GATEWAY_DYNAMIC_DEPENDENCIES, encoding="utf-8", mode="r"
        ) as f:
            dependencies = f.readlines()
    except IOError as e:
        if settings.GATEWAY_DYNAMIC_DEPENDENCIES != "":
            logger.error("Unable to open dynamic dependencies requirements file: %s", e)
        return {}

    dependencies = [dep.replace("\n", "") for dep in dependencies]
    dependencies = filter(lambda dep: not dep.startswith("#") and dep, dependencies)
    dependencies = [Requirement(dep) for dep in dependencies]

    return {dep.name: dep for dep in dependencies}


DEPENDENCY_REQUEST_URL = "https://github.com/Qiskit/qiskit-serverless/issues/new?template=pip_dependency_request.yaml"  # pylint: disable=line-too-long


def check_whitelisted(
    dependencies: List[Requirement], inject_version_if_missing=False
) -> List[Requirement]:
    """
    check if a list of dependencies are whitelisted.

    if "inject_version_if_missing" is True, the dependencies that has an empty version,
    will recieve the version of the whitelist.
    """
    whitelist_deps = create_dynamic_dependencies_whitelist()

    for dependency in dependencies:
        whitelisted_dependency = whitelist_deps.get(dependency.name)
        if not whitelisted_dependency:
            raise ValueError(
                f"Dependency `{dependency.name}` is not allowed. "
                f"You can request the dependency here: {DEPENDENCY_REQUEST_URL}"
            )

        req_version_list = list(dependency.specifier)
        if len(req_version_list) == 0:
            if inject_version_if_missing:
                dependency.specifier = whitelisted_dependency.specifier
            continue

        req_version = list(dependency.specifier)[0].version
        if not whitelisted_dependency.specifier.contains(req_version):
            raise ValueError(
                f"Dependency ({dependency.name}) version ({req_version})"
                f" is not allowed. Valid versions: {whitelisted_dependency}"
            )

    return dependencies
