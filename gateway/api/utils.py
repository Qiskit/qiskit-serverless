"""Utilities."""

from collections import OrderedDict
import json
import logging
import re
from typing import Any, Optional, Tuple, Callable, Dict, List
from django.conf import settings
from packaging.requirements import Requirement

import objsize

from api.domain.authentication.channel import Channel
from core.services.storage.path_builder import PathBuilder
from core.models import Job
from core.services.storage.enums.working_dir import WorkingDir

logger = logging.getLogger("utils")


def try_json_loads(data: str) -> Tuple[bool, Optional[dict]]:
    """Dumb check if data is json :)"""
    try:
        json_object = json.loads(data)
    except ValueError:
        return False, None
    return True, json_object


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

    extra.update(
        {
            "QISKIT_IBM_TOKEN": str(token),
            "QISKIT_IBM_CHANNEL": channel.value,
            "QISKIT_IBM_URL": settings.QISKIT_IBM_URL,
        }
    )

    if instance:
        extra.update(
            {
                "QISKIT_IBM_INSTANCE": str(instance),
                "ENV_JOB_GATEWAY_INSTANCE": str(instance),
            }
        )

    # DATA_PATH is where the function has the volume mounted (arguments, results, etc.)
    # In K8s/COS: volume user folder is mounted in /data using subPath={username}
    # in the values.yaml, so COS files are mounted from /{username} to /data,
    # so DATA_PATH is just /data (the user's folder)
    #
    # docker-compose (local mode): there's only one Ray node, and Gateway and Ray
    # shares the same volume program-artifacts which is
    #     `program-artifacts:/data` for Ray node
    #     `program-artifacts:/usr/src/app/media` for Gateway
    # However, the DATA_PATH value changes depending on the upload mode:
    #      - if the upload is via the `entrypoint` argument, the function will be a "user function",
    #         and the DATA_PATH follows the pattern /data/{username}
    #      - if the upload is via the `image` argument, a `provider` is required and the function will
    #        be a "provider function". In this case, the DATA_PATH will contain a sub-path after /data/{username}
    #        resulting in DATA_PATH = /data/{username}/{providername}/{imagename}
    if settings.RAY_CLUSTER_MODE_LOCAL:
        prefix = f"data/{job.author.username}"
        # only if provider is found, resolve path using path builder
        if job.program.provider is not None:
            sub_path = PathBuilder.sub_path(
                working_dir=WorkingDir.PROVIDER_STORAGE,
                username=job.author.username,
                function_title=job.program.title,
                provider_name=job.program.provider.name,
                extra_sub_path=None,
            )
        else:
            sub_path = ""
        # avoid double slash or trailing slash
        data_path = f"/{prefix}/{sub_path}".replace("//", "/").rstrip("/")
    else:
        data_path = "/data"

    return {
        **{
            "ENV_JOB_GATEWAY_TOKEN": str(token),
            "ENV_JOB_GATEWAY_HOST": str(settings.SITE_HOST),
            "ENV_JOB_ID_GATEWAY": str(job.id),
            "ENV_JOB_ARGUMENTS": arguments,
            "ENV_ACCESS_TRIAL": str(trial_mode),
            "DATA_PATH": data_path,
        },
        **extra,
    }


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
        with open(settings.GATEWAY_DYNAMIC_DEPENDENCIES, encoding="utf-8", mode="r") as f:
            dependencies = f.readlines()
    except IOError as e:
        if settings.GATEWAY_DYNAMIC_DEPENDENCIES != "":
            logger.error("Unable to open dynamic dependencies requirements file: %s", e)
        return {}

    # packaging.requirements.Requirement is a PEP 508-compliant parser. It won’t parse pip
    # “requirements.txt” extensions like --hash=..., -r other.txt, environment variable
    # substitution, or line continuations with '\'.
    dependencies = [dep.replace("\n", "") for dep in dependencies]
    dependencies = filter(lambda dep: not dep.startswith("#") and dep, dependencies)
    dependencies = [Requirement(dep) for dep in dependencies]

    return {dep.name: dep for dep in dependencies}


DEPENDENCY_REQUEST_URL = "https://github.com/Qiskit/qiskit-serverless/issues/new?template=pip_dependency_request.yaml"  # pylint: disable=line-too-long


def check_whitelisted(dependencies: List[Requirement], inject_version_if_missing=False) -> List[Requirement]:
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
