"""Utilities."""

import base64
from collections import OrderedDict
import inspect
import json
import logging
import os
import re
import time
import uuid
import sys
import platform
from typing import Any, Optional, Tuple, Type, Union, Callable, Dict, List
from django.conf import settings

from cryptography.fernet import Fernet
from ray.dashboard.modules.job.common import JobStatus
from parsley import makeGrammar
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
        except Exception as e:  # pylint: disable=broad-exception-caught
            if exceptions is None or isinstance(e, tuple(exceptions)):
                logger.log(
                    error_message_level,
                    "%s Retrying (%s/%s)...",
                    run,
                    num_retries,
                    error_message,
                )
                time.sleep(interval)
            else:
                raise

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
    pattern = re.compile("[^a-zA-Z0-9-.]")
    cluster_name = f"c-{re.sub(pattern, '-', username)}-{str(uuid.uuid4())[:8]}"
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


# Utilities for parsing python dependency information
# source: https://peps.python.org/pep-0508/#complete-grammar
RAW_DEPENDENCY_GRAMMAR = """
    wsp           = ' ' | '\t'
    version_cmp   = wsp* <'<=' | '<' | '!=' | '==' | '>=' | '>' | '~=' | '==='>
    version       = wsp* <( letterOrDigit | '-' | '_' | '.' | '*' | '+' | '!' )+>
    version_one   = version_cmp:op version:v wsp* -> (op, v)
    version_many  = version_one:v1 (wsp* ',' version_one)*:v2 -> [v1] + v2
    versionspec   = ('(' version_many:v ')' ->v) | version_many
    urlspec       = '@' wsp* <URI_reference>
    marker_op     = version_cmp | (wsp* 'in') | (wsp* 'not' wsp+ 'in')
    python_str_c  = (wsp | letter | digit | '(' | ')' | '.' | '{' | '}' |
                     '-' | '_' | '*' | '#' | ':' | ';' | ',' | '/' | '?' |
                     '[' | ']' | '!' | '~' | '`' | '@' | '$' | '%' | '^' |
                     '&' | '=' | '+' | '|' | '<' | '>' )
    dquote        = '"'
    squote        = '\\''
    python_str    = (squote <(python_str_c | dquote)*>:s squote |
                     dquote <(python_str_c | squote)*>:s dquote) -> s
    env_var       = ('python_version' | 'python_full_version' |
                     'os_name' | 'sys_platform' | 'platform_release' |
                     'platform_system' | 'platform_version' |
                     'platform_machine' | 'platform_python_implementation' |
                     'implementation_name' | 'implementation_version' |
                     'extra' # ONLY when defined by a containing layer
                     ):varname -> lookup(varname)
    marker_var    = wsp* (env_var | python_str)
    marker_expr   = marker_var:l marker_op:o marker_var:r -> (o, l, r)
                  | wsp* '(' marker:m wsp* ')' -> m
    marker_and    = marker_expr:l wsp* 'and' marker_expr:r -> ('and', l, r)
                  | marker_expr:m -> m
    marker_or     = marker_and:l wsp* 'or' marker_and:r -> ('or', l, r)
                      | marker_and:m -> m
    marker        = marker_or
    quoted_marker = ';' wsp* marker
    identifier_end = letterOrDigit | (('-' | '_' | '.' )* letterOrDigit)
    identifier    = < letterOrDigit identifier_end* >
    name          = identifier
    extras_list   = identifier:i (wsp* ',' wsp* identifier)*:ids -> [i] + ids
    extras        = '[' wsp* extras_list?:e wsp* ']' -> e
    name_req      = (name:n wsp* extras?:e wsp* versionspec?:v wsp* quoted_marker?:m
                     -> (n, e or [], v or [], m))
    url_req       = (name:n wsp* extras?:e wsp* urlspec:v (wsp+ | end) quoted_marker?:m
                     -> (n, e or [], v, m))
    specification = wsp* ( url_req | name_req ):s wsp* -> s
    # The result is a tuple - name, list-of-extras,
    # list-of-version-constraints-or-a-url, marker-ast or None


    URI_reference = <URI | relative_ref>
    URI           = scheme ':' hier_part ('?' query )? ( '#' fragment)?
    hier_part     = ('//' authority path_abempty) | path_absolute | path_rootless | path_empty
    absolute_URI  = scheme ':' hier_part ( '?' query )?
    relative_ref  = relative_part ( '?' query )? ( '#' fragment )?
    relative_part = '//' authority path_abempty | path_absolute | path_noscheme | path_empty
    scheme        = letter ( letter | digit | '+' | '-' | '.')*
    authority     = ( userinfo '@' )? host ( ':' port )?
    userinfo      = ( unreserved | pct_encoded | sub_delims | ':')*
    host          = IP_literal | IPv4address | reg_name
    port          = digit*
    IP_literal    = '[' ( IPv6address | IPvFuture) ']'
    IPvFuture     = 'v' hexdig+ '.' ( unreserved | sub_delims | ':')+
    IPv6address   = (
                      ( h16 ':'){6} ls32
                      | '::' ( h16 ':'){5} ls32
                      | ( h16 )?  '::' ( h16 ':'){4} ls32
                      | ( ( h16 ':')? h16 )? '::' ( h16 ':'){3} ls32
                      | ( ( h16 ':'){0,2} h16 )? '::' ( h16 ':'){2} ls32
                      | ( ( h16 ':'){0,3} h16 )? '::' h16 ':' ls32
                      | ( ( h16 ':'){0,4} h16 )? '::' ls32
                      | ( ( h16 ':'){0,5} h16 )? '::' h16
                      | ( ( h16 ':'){0,6} h16 )? '::' )
    h16           = hexdig{1,4}
    ls32          = ( h16 ':' h16) | IPv4address
    IPv4address   = dec_octet '.' dec_octet '.' dec_octet '.' dec_octet
    nz            = ~'0' digit
    dec_octet     = (
                      digit # 0-9
                      | nz digit # 10-99
                      | '1' digit{2} # 100-199
                      | '2' ('0' | '1' | '2' | '3' | '4') digit # 200-249
                      | '25' ('0' | '1' | '2' | '3' | '4' | '5') )# %250-255
    reg_name = ( unreserved | pct_encoded | sub_delims)*
    path = (
            path_abempty # begins with '/' or is empty
            | path_absolute # begins with '/' but not '//'
            | path_noscheme # begins with a non-colon segment
            | path_rootless # begins with a segment
            | path_empty ) # zero characters
    path_abempty  = ( '/' segment)*
    path_absolute = '/' ( segment_nz ( '/' segment)* )?
    path_noscheme = segment_nz_nc ( '/' segment)*
    path_rootless = segment_nz ( '/' segment)*
    path_empty    = pchar{0}
    segment       = pchar*
    segment_nz    = pchar+
    segment_nz_nc = ( unreserved | pct_encoded | sub_delims | '@')+
                    # non-zero-length segment without any colon ':'
    pchar         = unreserved | pct_encoded | sub_delims | ':' | '@'
    query         = ( pchar | '/' | '?')*
    fragment      = ( pchar | '/' | '?')*
    pct_encoded   = '%' hexdig
    unreserved    = letter | digit | '-' | '.' | '_' | '~'
    reserved      = gen_delims | sub_delims
    gen_delims    = ':' | '/' | '?' | '#' | '(' | ')?' | '@'
    sub_delims    = '!' | '$' | '&' | '\\'' | '(' | ')' | '*' | '+' | ',' | ';' | '='
    hexdig        = digit | 'a' | 'A' | 'b' | 'B' | 'c' | 'C' | 'd' | 'D' | 'e' | 'E' | 'f' | 'F'
"""


def create_dependency_grammar(grammar=RAW_DEPENDENCY_GRAMMAR):
    """Create dependency grammar."""

    if hasattr(sys, "implementation"):
        sys_version = sys.implementation.version
        version = f"{sys_version.major}.{sys_version.minor}.{sys_version.micro}"
        kind = sys.implementation.version.releaselevel
        if kind != "final":
            version += kind[0] + str(sys.implementation.version.serial)
        implementation_version = version
        implementation_name = sys.implementation.name
    else:
        implementation_version = "0"
        implementation_name = ""
    bindings = {
        "implementation_name": implementation_name,
        "implementation_version": implementation_version,
        "os_name": os.name,
        "platform_machine": platform.machine(),
        "platform_python_implementation": platform.python_implementation(),
        "platform_release": platform.release(),
        "platform_system": platform.system(),
        "platform_version": platform.version(),
        "python_full_version": platform.python_version(),
        "python_version": ".".join(platform.python_version_tuple()[:2]),
        "sys_platform": sys.platform,
    }

    dependency_grammar = makeGrammar(grammar, {"lookup": bindings.__getitem__})
    return dependency_grammar


def parse_dependency(dep, grammar):
    """Parse dependency."""
    parsed = grammar(dep).specification()
    dep_name = parsed[0]
    dep_ver = parsed[2]

    return dep_name, dep_ver


def create_dependency_allowlist():
    """
    Create dictionary with allowed dependencies and versions.

    Sample format:
        allowlist = { "wheel": ["0.44.0", "0.43.2"] }
    where the values for each key are allowed versions of dependency.
    """
    try:
        with open(settings.GATEWAY_ALLOWLIST_CONFIG, encoding="utf-8", mode="r") as f:
            allowlist = json.load(f)
    except IOError as e:
        logger.error("Unable to open allowlist config file: %s", e)
        raise ValueError("Unable to open allowlist config file") from e
    except ValueError as e:
        logger.error("Unable to decode dependency allowlist: %s", e)
        raise ValueError("Unable to decode dependency allowlist") from e

    return allowlist


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
