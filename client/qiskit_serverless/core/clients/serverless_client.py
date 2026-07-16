# This code is a Qiskit project.
#
# (C) Copyright IBM 2022.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""
================================================
Provider (:mod:`qiskit_serverless.core.client`)
================================================

.. currentmodule:: qiskit_serverless.core.client

Qiskit Serverless provider
===========================

.. autosummary::
    :toctree: ../stubs/

    ServerlessClient
"""

# pylint: disable=duplicate-code,too-many-lines
import json
import os.path
import os
import re
import tarfile
import warnings
from pathlib import Path
from urllib.parse import urlparse
from dataclasses import asdict
from typing import Optional, List, Dict, Any, Union
from collections.abc import Callable

import requests
from opentelemetry import trace
from qiskit.providers.backend import BackendV2 as Backend
from qiskit.providers.exceptions import QiskitBackendNotFoundError
from qiskit_ibm_runtime import QiskitRuntimeService, IBMBackend
from qiskit_ibm_runtime.accounts.exceptions import InvalidAccountError

from qiskit_serverless.core.constants import (
    REQUESTS_TIMEOUT,
    ENV_GATEWAY_PROVIDER_HOST,
    ENV_GATEWAY_PROVIDER_VERSION,
    ENV_GATEWAY_PROVIDER_TOKEN,
    GATEWAY_PROVIDER_VERSION_DEFAULT,
    IBM_SERVERLESS_HOST_URL,
    MAX_ARTIFACT_FILE_SIZE_MB,
    USAGE_LOW_THRESHOLD_SECONDS,
    USAGE_ZERO_EPSILON_SECONDS,
)
from qiskit_serverless.core.client import BaseClient
from qiskit_serverless.core.decorators import trace_decorator_factory
from qiskit_serverless.core.enums import Channel
from qiskit_serverless.core.files import GatewayFilesClient
from qiskit_serverless.core.job import (
    Job,
    Configuration,
    _map_status_to_serverless,
)
from qiskit_serverless.core.job_event import JobEvent

from qiskit_serverless.core.function import (
    QiskitFunction,
    RunService,
    RunnableQiskitFunction,
)

from qiskit_serverless.exception import QiskitServerlessException
from qiskit_serverless.utils.http import get_headers
from qiskit_serverless.utils.json import (
    safe_json_request_as_dict,
    safe_json_request_as_list,
    safe_json_request,
    raise_for_non_ok_response,
)
from qiskit_serverless.utils.formatting import format_provider_name_and_title
from qiskit_serverless.serializers.program_serializers import (
    QiskitObjectsEncoder,
    QiskitObjectsDecoder,
)

_trace_job = trace_decorator_factory("job")
_trace_functions = trace_decorator_factory("function")


class ServerlessClient(BaseClient):  # pylint: disable=too-many-public-methods
    """
    A client for connecting to a specified host.

    Example:
        >>> client = ServerlessClient(
        >>>    name="<NAME>",
        >>>    host="<HOST>",
        >>>    token="<TOKEN>",
        >>>    instance="<CRN>",
        >>> )
    """

    def __init__(  # pylint:  disable=too-many-positional-arguments
        self,
        name: Optional[str] = None,
        host: Optional[str] = None,
        version: Optional[str] = None,
        token: Optional[str] = None,
        instance: Optional[str] = None,
        channel: Optional[str] = None,
    ):
        """
        Initializes the ServerlessClient instance.

        Args:
            name: (deprecated) name of client - will be removed in a future release
            host: host of gateway. If None, it uses the ENV_GATEWAY_PROVIDER_HOST env var
            version: version of gateway
            token: authorization token
            instance: IBM Cloud CRN
            channel: identifies the method to use to authenticate the user
        """
        if name:
            warnings.warn(
                "The 'name' attribute is deprecated and will be removed in a future release.",
                DeprecationWarning,
                stacklevel=2,
            )
        resolved_name = name or "gateway-client"
        host = host or os.environ.get(ENV_GATEWAY_PROVIDER_HOST)
        if host is None:
            raise QiskitServerlessException("Please provide `host` of gateway.")

        version = version or os.environ.get(ENV_GATEWAY_PROVIDER_VERSION)
        if version is None:
            version = GATEWAY_PROVIDER_VERSION_DEFAULT

        token = token or os.environ.get(ENV_GATEWAY_PROVIDER_TOKEN)
        if token is None:
            raise QiskitServerlessException("Authentication credentials must be provided in form of `token`.")

        channel = channel or Channel.IBM_QUANTUM_PLATFORM.value
        try:
            channel_enum = Channel(channel)
        except ValueError as error:
            raise ValueError(
                "Your channel value is not correct. Use one of the available channels: "
                f"{Channel.LOCAL.value}, "
                f"{Channel.IBM_CLOUD.value}, {Channel.IBM_QUANTUM_PLATFORM.value}"
            ) from error

        if channel_enum is Channel.IBM_CLOUD and instance is None:
            raise QiskitServerlessException("Authentication with IBM Cloud requires to pass the CRN as an instance.")

        if channel_enum is Channel.IBM_QUANTUM_PLATFORM and instance is None:
            raise QiskitServerlessException(
                "Authentication with IBM Quantum Platform requires to pass the CRN as an instance."
            )

        # Pass name=None so BaseClient does not emit a second deprecation
        # warning; the warning above is the single one users should see.
        super().__init__(None, host, token, instance, channel)
        self.name = resolved_name
        self.version = version
        self._verify_credentials()

        self._files_client = GatewayFilesClient(self.host, self.token, self.version, self.instance, self.channel)

    @classmethod
    def from_dict(cls, dictionary: dict):
        return ServerlessClient(**dictionary)

    def _verify_credentials(self):
        """Verify against the API that the credentials are correct."""
        try:
            safe_json_request(
                request=lambda: requests.get(
                    url=f"{self.host}/api/v1/programs/",
                    headers=get_headers(token=self.token, instance=self.instance, channel=self.channel),
                    timeout=REQUESTS_TIMEOUT,
                )
            )
        except QiskitServerlessException as reason:
            raise QiskitServerlessException(f"Credentials couldn't be verified: {reason}") from reason

    def dependencies_versions(self):
        """Get the list of available dependencies and its versions for creating functions"""
        return safe_json_request_as_list(
            request=lambda: requests.get(
                url=f"{self.host}/api/{self.version}/dependencies-versions/",
                headers=get_headers(token=self.token, instance=self.instance),
                timeout=REQUESTS_TIMEOUT,
            )
        )

    ####################
    ####### JOBS #######
    ####################

    @_trace_job("list")
    def jobs(self, function: Optional[QiskitFunction] = None, **kwargs) -> List[Job]:
        """Retrieve a list of jobs with optional filtering.

        Args:
            function (QiskitFunction): The function that created the jobs we want to retrieve.
            limit (int, optional): Maximum number of jobs to return. Defaults to 10.
            offset (int, optional): Number of jobs to skip. Defaults to 0.
            status (str, optional): Filter by job status.
            created_after (str, optional): Filter jobs created after this timestamp.
            **kwargs: Additional query parameters.

        Returns:
            List[Job]: List of Job objects matching the criteria.
        """
        limit = kwargs.get("limit", 10)
        kwargs["limit"] = limit
        offset = kwargs.get("offset", 0)
        kwargs["offset"] = offset
        status = kwargs.get("status", None)
        if status:
            status, _ = _map_status_to_serverless(status)
        kwargs["status"] = status
        created_after = kwargs.get("created_after", None)
        kwargs["created_after"] = created_after

        if function:
            kwargs["function"] = function.title
            kwargs["provider"] = function.provider

        response_data = safe_json_request_as_dict(
            request=lambda: requests.get(
                f"{self.host}/api/{self.version}/jobs/",
                params=kwargs,
                headers=get_headers(token=self.token, instance=self.instance, channel=self.channel),
                timeout=REQUESTS_TIMEOUT,
            )
        )

        return [
            Job(
                job.get("id"),
                job_service=self,
                raw_data=job,
                compute_profile=job.get("compute_profile"),
            )
            for job in response_data.get("results", [])
        ]

    @_trace_job("provider_list")
    def provider_jobs(self, function: Optional[QiskitFunction], **kwargs) -> List[Job]:
        """Retrieve jobs for a specific provider and function.

        Args:
            function (QiskitFunction): Function object.
            limit (int, optional): Maximum number of jobs to return. Defaults to 10.
            offset (int, optional): Number of jobs to skip. Defaults to 0.
            status (str, optional): Filter by job status.
            created_after (str, optional): Filter jobs created after this timestamp.
            **kwargs: Additional query parameters.

        Returns:
            List[Job]: List of Job objects for the specified provider and function.

        Raises:
            QiskitServerlessException: If the function doesn't have an associated provider.
        """
        if not function.provider:
            raise QiskitServerlessException("`function` doesn't have a provider.")

        limit = kwargs.get("limit", 10)
        kwargs["limit"] = limit
        offset = kwargs.get("offset", 0)
        kwargs["offset"] = offset
        status = kwargs.get("status", None)
        if status:
            status, _ = _map_status_to_serverless(status)
        kwargs["status"] = status
        created_after = kwargs.get("created_after", None)
        kwargs["created_after"] = created_after

        if function:
            kwargs["function"] = function.title
            kwargs["provider"] = function.provider

        response_data = safe_json_request_as_dict(
            request=lambda: requests.get(
                f"{self.host}/api/{self.version}/jobs/provider/",
                params=kwargs,
                headers=get_headers(token=self.token, instance=self.instance, channel=self.channel),
                timeout=REQUESTS_TIMEOUT,
            )
        )

        return [
            Job(
                job.get("id"),
                job_service=self,
                raw_data=job,
                compute_profile=job.get("compute_profile"),
            )
            for job in response_data.get("results", [])
        ]

    @_trace_job("get")
    def job(self, job_id: str) -> Optional[Job]:
        url = f"{self.host}/api/{self.version}/jobs/{job_id}/"
        response_data = safe_json_request_as_dict(
            request=lambda: requests.get(
                url,
                headers=get_headers(token=self.token, instance=self.instance, channel=self.channel),
                params={"with_result": "false"},
                timeout=REQUESTS_TIMEOUT,
            )
        )

        job = None
        job_id = response_data.get("id")
        if job_id is not None:
            job = Job(
                job_id=job_id,
                job_service=self,
                compute_profile=response_data.get("compute_profile"),
            )

        return job

    def run(
        self,
        program: Union[QiskitFunction, str],
        arguments: Optional[Dict[str, Any]] = None,
        config: Optional[Configuration] = None,
        provider: Optional[str] = None,
        *,
        compute_profile: Optional[str] = None,
    ) -> Job:
        if isinstance(program, QiskitFunction):
            title = program.title
            provider = program.provider
        else:
            title = str(program)

        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("job.run") as span:
            span.set_attribute("function", title)
            span.set_attribute("provider", provider)
            span.set_attribute("arguments", str(arguments))

            url = f"{self.host}/api/{self.version}/programs/run/"

            data = {
                "title": title,
                "provider": provider,
                "compute_profile": compute_profile,
                "arguments": json.dumps(arguments or {}, cls=QiskitObjectsEncoder),
            }  # type: Dict[str, Any]
            if config:
                data["config"] = asdict(config)
            else:
                data["config"] = asdict(Configuration())

            response_data = safe_json_request_as_dict(
                request=lambda: requests.post(
                    url=url,
                    json=data,
                    headers=get_headers(token=self.token, instance=self.instance, channel=self.channel),
                    timeout=REQUESTS_TIMEOUT,
                )
            )
            job_id = response_data.get("id")
            span.set_attribute("job.id", job_id)

        return Job(
            job_id,
            job_service=self,
            compute_profile=response_data.get("compute_profile"),
        )

    def get_job_data(self, job_id: str) -> Optional[dict]:
        return (
            safe_json_request_as_dict(
                request=lambda: requests.get(
                    f"{self.host}/api/{self.version}/jobs/{job_id}/",
                    params={"with_result": "false"},
                    headers=get_headers(token=self.token, instance=self.instance, channel=self.channel),
                    timeout=REQUESTS_TIMEOUT,
                )
            )
            or None
        )

    @_trace_job
    def status(self, job_id: str):
        default_status = "Unknown"
        response_data = safe_json_request_as_dict(
            request=lambda: requests.get(
                f"{self.host}/api/{self.version}/jobs/{job_id}/",
                params={"with_result": "false"},
                headers=get_headers(token=self.token, instance=self.instance, channel=self.channel),
                timeout=REQUESTS_TIMEOUT,
            )
        )

        status = response_data.get("status", default_status)
        sub_status = response_data.get("sub_status")
        if status == Job.RUNNING and sub_status is not None:
            return sub_status

        return status

    @_trace_job
    def stop(self, job_id: str, service: Optional[QiskitRuntimeService] = None):

        if not service:
            try:
                service = QiskitRuntimeService(channel=self.channel, instance=self.instance, token=self.token)
            except InvalidAccountError:
                warnings.warn(
                    "No QiskitRuntimeService can be associated to the given token and instance. "
                    "Continuing without a QiskitRuntimeService."
                )
                service = None
        data: dict[str, Any] = {
            "service": json.dumps(service, cls=QiskitObjectsEncoder),
        }

        response_data = safe_json_request_as_dict(
            request=lambda: requests.post(
                f"{self.host}/api/{self.version}/jobs/{job_id}/stop/",
                headers=get_headers(token=self.token, instance=self.instance, channel=self.channel),
                timeout=REQUESTS_TIMEOUT,
                json=data,
            )
        )

        return response_data.get("message")

    @_trace_job
    def result(self, job_id: str) -> Dict[str, Any]:
        gateway_url = f"{self.host}/api/{self.version}/jobs/{job_id}/result/"
        response = requests.get(
            gateway_url,
            headers=get_headers(token=self.token, instance=self.instance, channel=self.channel),
            timeout=REQUESTS_TIMEOUT,
        )
        if response.status_code == 204:
            return {}
        # Any non-OK response (from the gateway, COS, or an intermediary such as
        # Cloudflare returning a block page) is surfaced with its status and body
        # instead of being fed to the JSON parser as a cryptic decoding error.
        raise_for_non_ok_response(response)
        # Not all redirects go to COS — HTTP→HTTPS redirects stay on the same host.
        # Checking the hostname detects only redirects to an external host (COS/MinIO).
        redirected_to_cos = urlparse(response.url).hostname != urlparse(gateway_url).hostname
        if redirected_to_cos:
            return json.loads(response.text, cls=QiskitObjectsDecoder)
        return json.loads(response.json().get("result", "{}") or "{}", cls=QiskitObjectsDecoder)

    @_trace_job
    def logs(self, job_id: str):
        gateway_url = f"{self.host}/api/{self.version}/jobs/{job_id}/logs/"
        response = requests.get(
            gateway_url,
            headers=get_headers(token=self.token, instance=self.instance, channel=self.channel),
            timeout=REQUESTS_TIMEOUT,
        )
        if response.status_code == 204:
            return "No logs yet."
        # Any non-OK response (from the gateway, COS, or an intermediary such as
        # Cloudflare returning a block page) is surfaced with its status and body
        # instead of being fed to the JSON parser as a cryptic decoding error.
        raise_for_non_ok_response(response)
        # Not all redirects go to COS — HTTP→HTTPS redirects stay on the same host.
        # Checking the hostname detects only redirects to an external host (COS/MinIO).
        redirected_to_cos = urlparse(response.url).hostname != urlparse(gateway_url).hostname
        if redirected_to_cos:
            return response.text
        return safe_json_request_as_dict(request=lambda: response).get("logs")

    @_trace_job
    def provider_logs(self, job_id: str):
        gateway_url = f"{self.host}/api/{self.version}/jobs/{job_id}/provider-logs/"
        response = requests.get(
            gateway_url,
            headers=get_headers(token=self.token, instance=self.instance, channel=self.channel),
            timeout=REQUESTS_TIMEOUT,
        )
        if response.status_code == 204:
            return "No logs yet."
        # Any non-OK response (from the gateway, COS, or an intermediary such as
        # Cloudflare returning a block page) is surfaced with its status and body
        # instead of being fed to the JSON parser as a cryptic decoding error.
        raise_for_non_ok_response(response)
        # Not all redirects go to COS — HTTP→HTTPS redirects stay on the same host.
        # Checking the hostname detects only redirects to an external host (COS/MinIO).
        redirected_to_cos = urlparse(response.url).hostname != urlparse(gateway_url).hostname
        if redirected_to_cos:
            return response.text
        return safe_json_request_as_dict(request=lambda: response).get("logs")

    @_trace_job
    def runtime_jobs(self, job_id: str, runtime_session: Optional[str] = None) -> list[str]:
        """Retrieve Qiskit IBM Runtime job ids that correspond to a
        given serverless job_id execution and, optionally, filtered by session id."""
        response_data = safe_json_request_as_dict(
            request=lambda: requests.get(
                f"{self.host}/api/{self.version}/jobs/{job_id}/runtime_jobs/",
                headers=get_headers(token=self.token, instance=self.instance, channel=self.channel),
                timeout=REQUESTS_TIMEOUT,
            )
        )

        if runtime_session:
            return [
                job.get("runtime_job")
                for job in response_data.get("runtime_jobs", [])
                if job.get("runtime_session") == runtime_session
            ]
        return [job.get("runtime_job") for job in response_data.get("runtime_jobs", [])]

    @_trace_job
    def runtime_sessions(self, job_id: str):
        """Retrieve Qiskit IBM Runtime session ids that correspond to a
        given serverless job_id execution."""
        response_data = safe_json_request_as_dict(
            request=lambda: requests.get(
                f"{self.host}/api/{self.version}/jobs/{job_id}/runtime_jobs/",
                headers=get_headers(token=self.token, instance=self.instance, channel=self.channel),
                timeout=REQUESTS_TIMEOUT,
            )
        )
        runtime_jobs = response_data.get("runtime_jobs", [])
        out_sessions = sorted({job["runtime_session"] for job in runtime_jobs if job.get("runtime_session")})
        return out_sessions

    def filtered_logs(self, job_id: str, **kwargs):
        all_logs = self.logs(job_id=job_id)
        included = ""
        include = kwargs.get("include")
        if include is not None:
            for line in all_logs.split("\n"):
                if re.search(include, line) is not None:
                    included = included + line + "\n"
        else:
            included = all_logs

        excluded = ""
        exclude = kwargs.get("exclude")
        if exclude is not None:
            for line in included.split("\n"):
                if line != "" and re.search(exclude, line) is None:
                    excluded = excluded + line + "\n"
        else:
            excluded = included
        return excluded

    def events(self, job_id: str, **kwargs) -> list[JobEvent]:
        """Returns events of the job.
        Args:
            job_id: The job id
        """
        response_data = safe_json_request_as_list(
            request=lambda: requests.get(
                f"{self.host}/api/{self.version}/jobs/{job_id}/events/",
                params=kwargs,
                headers=get_headers(token=self.token, instance=self.instance, channel=self.channel),
                timeout=REQUESTS_TIMEOUT,
            )
        )

        return [JobEvent.from_json(event) for event in response_data]

    #########################
    ####### Functions #######
    #########################

    def upload(self, program: QiskitFunction) -> Optional[RunnableQiskitFunction]:
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("function.upload") as span:
            span.set_attribute("function", program.title)
            url = f"{self.host}/api/{self.version}/programs/upload/"

            if program.image:
                # upload function with custom image
                function_uploaded = _upload_with_docker_image(
                    program=program,
                    url=url,
                    token=self.token,
                    span=span,
                    client=self,
                    instance=self.instance,
                    channel=self.channel,
                )
            elif program.entrypoint:
                # upload function with artifact
                function_uploaded = _upload_with_artifact(
                    program=program,
                    url=url,
                    token=self.token,
                    span=span,
                    client=self,
                    instance=self.instance,
                    channel=self.channel,
                )
            else:
                raise QiskitServerlessException("Function must either have `entrypoint` or `image` specified.")

        return function_uploaded

    @_trace_functions("list")
    def functions(self, **kwargs) -> List[RunnableQiskitFunction]:
        """Returns list of available functions."""
        response_data = safe_json_request_as_list(
            request=lambda: requests.get(
                f"{self.host}/api/{self.version}/programs",
                headers=get_headers(token=self.token, instance=self.instance, channel=self.channel),
                params=kwargs,
                timeout=REQUESTS_TIMEOUT,
            )
        )

        for program_data in response_data:
            program_data["client"] = self

        return [RunnableQiskitFunction.from_json(program_data) for program_data in response_data]

    @_trace_functions("get_by_title")
    def function(self, title: str, provider: Optional[str] = None) -> Optional[RunnableQiskitFunction]:
        """Returns program based on parameters."""
        provider, title = format_provider_name_and_title(request_provider=provider, title=title)

        response_data = safe_json_request_as_dict(
            request=lambda: requests.get(
                f"{self.host}/api/{self.version}/programs/get_by_title/{title}",
                headers=get_headers(token=self.token, instance=self.instance, channel=self.channel),
                params={"provider": provider},
                timeout=REQUESTS_TIMEOUT,
            )
        )

        response_data["client"] = self
        the_function = RunnableQiskitFunction.from_json(response_data)
        return the_function

    #####################
    ####### FILES #######
    #####################

    def files(self, function: QiskitFunction) -> List[str]:
        """Returns the list of files available for the user in the Qiskit Function folder."""
        return self._files_client.list(function)

    def provider_files(self, function: QiskitFunction) -> List[str]:
        """Returns the list of files available for the provider in the Qiskit Function folder."""
        return self._files_client.provider_list(function)

    def file_download(
        self,
        file: str,
        function: QiskitFunction,
        target_name: Optional[str] = None,
        download_location: str = "./",
    ):
        """Download a file available to the user for the specific Qiskit Function."""
        return self._files_client.download(file, download_location, function, target_name)

    def provider_file_download(
        self,
        file: str,
        function: QiskitFunction,
        target_name: Optional[str] = None,
        download_location: str = "./",
    ):
        """Download a file available to the provider for the specific Qiskit Function."""
        return self._files_client.provider_download(file, download_location, function, target_name)

    def file_delete(self, file: str, function: QiskitFunction):
        """Deletes a file available to the user for the specific Qiskit Function."""
        return self._files_client.delete(file, function)

    def provider_file_delete(self, file: str, function: QiskitFunction):
        """Deletes a file available to the provider for the specific Qiskit Function."""
        return self._files_client.provider_delete(file, function)

    def file_upload(self, file: str, function: QiskitFunction):
        """Uploads a file in the specific user's Qiskit Function folder."""
        return self._files_client.upload(file, function)

    def provider_file_upload(self, file: str, function: QiskitFunction):
        """Uploads a file in the specific provider's Qiskit Function folder."""
        return self._files_client.provider_upload(file, function)


class IBMServerlessClient(ServerlessClient):
    """
    A client for connecting to the IBM serverless host.

    Credentials can be saved to disk by calling the `save_account()` method::

        from qiskit_serverless import IBMServerlessClient
        IBMServerlessClient.save_account(token=<INSERT_IBM_QUANTUM_TOKEN>, instance=<INSERT_CRN>)

    Once the credentials are saved, you can simply instantiate the client with no
    constructor args, as shown below.

        from qiskit_serverless import IBMServerlessClient
        client = IBMServerlessClient()

    Instead of saving credentials to disk, you can also set the environment variable
    ENV_GATEWAY_PROVIDER_TOKEN and then instantiate the client as below::

        from qiskit_serverless import IBMServerlessClient
        client = IBMServerlessClient()

    You can also enable an account just for the current session by instantiating the
    provider with the API token::

        from qiskit_serverless import IBMServerlessClient
        client = IBMServerlessClient(token=<INSERT_IBM_QUANTUM_TOKEN>, instance=<INSERT_CRN>)
    """

    def __init__(
        self,
        token: Optional[str] = None,
        name: Optional[str] = None,
        instance: Optional[str] = None,
        channel: Optional[str] = None,
        *,
        host: Optional[str] = None,
    ):
        """
        Initialize a client with access to an IBMQ-provided remote cluster.

        If a ``token`` is used to initialize an instance, the ``name`` argument
        will be ignored.

        If only a ``name`` is provided, the token for the named account will
        be retrieved from the user's local IBM Quantum account config file.

        If neither argument is provided, the token will be searched for in the
        environment variables and also in the local IBM Quantum account config
        file using the default account name.

        Args:
            host: host of gateway. Optional. It uses IBM_SERVERLESS_HOST_URL env var or IBM host
            token: IBM quantum token
            name: Name of the account to load
            instance: IBM Cloud CRN
            channel: identifies the method to use to authenticate the user
        """

        channel = channel or Channel.IBM_QUANTUM_PLATFORM.value  # For backwards compatibility

        # Initialize QiskitRuntimeService
        self._service = QiskitRuntimeService(channel=channel, token=token, name=name, instance=instance)
        self.account = self._service._account

        # Per-instance cache keyed by backend name; populated lazily by backends() or _get_backend().
        # Instance-level (not class-level) to avoid cross-client leakage.
        self._backends_cache: Dict[str, Any] = {}

        super().__init__(
            channel=self.account.channel,
            token=self.account.token,
            instance=self.account.instance,
            host=host if host else IBM_SERVERLESS_HOST_URL,
        )

    @staticmethod
    def save_account(
        token: Optional[str] = None,
        name: Optional[str] = None,
        overwrite: Optional[bool] = False,
        instance: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> None:
        """
        Save the account to disk for future use.

        Args:
            token: IBM Quantum API token
            name: Name of the account to save
            overwrite: ``True`` if the existing account is to be overwritten
            instance: IBM Cloud CRN
            channel: identifies the method to use to authenticate the user
        """
        try:
            QiskitRuntimeService.save_account(
                token=token,
                name=name,
                overwrite=overwrite,
                instance=instance,
                channel=channel,
            )
        except InvalidAccountError as ex:
            raise QiskitServerlessException(f"Invalid format in account inputs - {ex}") from ex

    def usage(self) -> dict[str, Any]:
        """Return runtime usage information for the active instance.

        Exposes the underlying :meth:`QiskitRuntimeService.usage` method to retrieve
        the instance's runtime quota information, including ``usage_remaining_seconds``
        and ``usage_limit_reached``.

        Returns:
            A dictionary containing usage information as reported by the runtime service.

        Raises:
            QiskitServerlessException: If the usage information cannot be retrieved.
        """
        try:
            return self._service.usage()
        except Exception as exc:  # pylint: disable=broad-except
            raise QiskitServerlessException(
                f"Failed to retrieve usage information for instance '{self.instance}': {exc}"
            ) from exc

    def backends(  # pylint: disable=too-many-positional-arguments
        self,
        refresh_cache: bool = False,
        name: str | None = None,
        min_num_qubits: int | None = None,
        filters: Callable[[IBMBackend], bool] | None = None,
        **kwargs: Any,
    ) -> list[IBMBackend]:
        """Return backends accessible through this instance.

        Exposes the underlying :meth:`QiskitRuntimeService.backends` method with
        per-instance caching. Results are cached after the first call; use
        ``refresh_cache=True`` to force a refresh.

        Args:
            refresh_cache: If ``True``, refresh the cache by fetching backends from the service.
            name: Backend name to filter by.
            min_num_qubits: Minimum number of qubits the backend must have.
            filters: More complex filters, such as lambda functions.
                For example::

                    client.backends(filters=lambda b: b.max_shots > 50000)
                    client.backends(filters=lambda x: "rz" in x.basis_gates)

            **kwargs: Simple filters that require a specific value for an attribute in
                backend configuration or status.
                Examples::

                    # Get backends with at least 127 qubits
                    client.backends(min_num_qubits=127)

                For the full list of backend attributes, see the `IBMBackend class documentation
                <https://quantum.cloud.ibm.com/docs/api/qiskit-ibm-runtime/qiskit-runtime-service#backends>`_

        Returns:
            List of available backends that match the filter criteria.

        Raises:
            QiskitServerlessException: If the backend listing call fails.
        """
        if not refresh_cache and self._backends_cache:
            # cache is available and refresh flag is false
            return list(self._backends_cache.values())
        try:
            backend_list = self._service.backends(
                name=name,
                min_num_qubits=min_num_qubits,
                filters=filters,
                **kwargs,
            )
        except Exception as exc:
            raise QiskitServerlessException(
                f"Failed to retrieve backends for instance '{self.instance}': {exc}"
            ) from exc

        # deleting cached backends as they could have unavailable backends and update with new accessible backends
        self._backends_cache = {}

        for backend in backend_list:
            self._backends_cache[backend.name] = backend

        return backend_list

    def backend(self, name: str, **kwargs: Any) -> Backend:
        """Fetch a single backend by name and update the cache.

        Exposes the underlying :meth:`QiskitRuntimeService.backend` method to perform
        a targeted backend lookup. This is more efficient than listing all backends
        and validates that the caller has access to the requested backend. The cache
        is updated on every call to reflect current access permissions.

        Args:
            name: Name of the backend (e.g., ``"ibm_torino"``).
            **kwargs: Simple filters that require a specific value for an attribute in
                backend configuration or status.
                For the full list of backend attributes, see the `IBMBackend class documentation
                <https://quantum.cloud.ibm.com/docs/api/qiskit-ibm-runtime/qiskit-runtime-service#backend>`_

        Returns:
            Backend matching the specified name.

        Raises:
            QiskitServerlessException: If the backend is not found or is inaccessible.
        """
        try:
            backend = self._service.backend(name=name, **kwargs)
        except QiskitBackendNotFoundError as exc:
            raise QiskitServerlessException(
                f"Backend '{name}' is not available or you do not have access to it "
                f"with instance '{self.instance}'. "
                f"Call client.backends() to list accessible backends."
            ) from exc
        except Exception as exc:
            raise QiskitServerlessException(f"Failed to retrieve backend '{name}': {exc}") from exc

        self._backends_cache[name] = backend
        return backend

    def least_busy(
        self,
        min_num_qubits: int | None = None,
        filters: Callable[[IBMBackend], bool] | None = None,
        **kwargs: Any,
    ) -> IBMBackend:
        """Return the least busy backend matching the specified criteria.

        Exposes the underlying :meth:`QiskitRuntimeService.least_busy` method to find
        the backend with the fewest pending jobs. The result is cached in the instance.

        Args:
            min_num_qubits: Minimum number of qubits the backend must have.
            filters: Filters can be defined as for the :meth:`backends` method.
                Example::

                    client.least_busy(min_num_qubits=5, operational=True)

            **kwargs: Additional filters for backend configuration or status attributes.

        Returns:
            The backend with the fewest number of pending jobs that matches the criteria.

        Raises:
            QiskitServerlessException: If no backend matches the criteria or the call fails.
        """
        try:
            backend = self._service.least_busy(
                min_num_qubits=min_num_qubits,
                filters=filters,
                **kwargs,
            )
        except QiskitBackendNotFoundError as exc:
            raise QiskitServerlessException(
                f"No available backend matches the criteria with instance '{self.instance}'. "
                f"Call client.backends() to list accessible backends."
            ) from exc
        except Exception as exc:
            raise QiskitServerlessException(f"Failed to retrieve backend: {exc}") from exc
        self._backends_cache[backend.name] = backend
        return backend

    def _check_usage(self, suppress_low_usage_warning: bool = False) -> None:
        """Check instance runtime quota and warn or raise if insufficient.

        Retrieves ``usage_remaining_seconds`` from :meth:`usage`. If the key is absent,
        the plan is unlimited and no action is taken. Transient errors from the usage
        endpoint are downgraded to a warning to avoid blocking job submission.

        Thresholds are configurable via environment variables (see constants.py):

        - ``USAGE_ZERO_EPSILON_SECONDS`` (default 1 s): Raises an exception when
          remaining time is at or below this threshold.
        - ``USAGE_LOW_THRESHOLD_SECONDS`` (default 600 s): Emits a warning when
          remaining time is below this threshold (unless suppressed).

        Args:
            suppress_low_usage_warning: If ``True``, suppress the warning when remaining
                quota is below ``USAGE_LOW_THRESHOLD_SECONDS``. The exception for
                exhausted quota (at or below ``USAGE_ZERO_EPSILON_SECONDS``) is still raised.

        Raises:
            QiskitServerlessException: When remaining quota is at or below
                ``USAGE_ZERO_EPSILON_SECONDS``, or when ``usage_limit_reached`` is
                ``True`` with no remaining time recorded.
        """
        try:
            usage = self.usage()
        except Exception as exc:  # pylint: disable=broad-except
            warnings.warn(
                f"Could not retrieve usage information for instance '{self.instance}': {exc}. "
                "Proceeding with job submission; verify your instance quota manually."
            )
            return

        remaining = usage.get("usage_remaining_seconds")
        limit_reached = usage.get("usage_limit_reached", False)

        if remaining is None and not limit_reached:
            return

        # usage_limit_reached without a recorded remaining value → treat as zero.
        if limit_reached and remaining is None:
            remaining = 0.0

        if remaining is not None and remaining <= USAGE_ZERO_EPSILON_SECONDS:
            raise QiskitServerlessException(
                f"Instance '{self.instance}' has no remaining runtime quota "
                f"(remaining: {remaining:.2f}s). "
                "The job would wait indefinitely for runtime resources. "
                "Check your instance quota at https://quantum.cloud.ibm.com/instances."
            )

        if not suppress_low_usage_warning and remaining is not None and remaining <= USAGE_LOW_THRESHOLD_SECONDS:
            warnings.warn(
                f"Instance '{self.instance}' has low remaining runtime quota "
                f"({remaining:.0f}s remaining, threshold: {USAGE_LOW_THRESHOLD_SECONDS:.0f}s). "
                "Consider checking your quota before submitting long-running jobs. "
                "Check https://quantum.cloud.ibm.com/instances for details."
            )

    def run(  # pylint: disable=too-many-positional-arguments
        self,
        program: Union[QiskitFunction, str],
        arguments: Optional[Dict[str, Any]] = None,
        config: Optional[Configuration] = None,
        provider: Optional[str] = None,
        *,
        compute_profile: Optional[str] = None,
        suppress_low_usage_warning: bool = False,
    ) -> "Job":
        """Run a Qiskit Function with pre-flight validation before submitting to the gateway.

        Checks are performed before delegating to ``ServerlessClient.run``. Checks include instance has no
        remaining runtime; warns when low and check accessibility to the backed
        Args:
            program: ``QiskitFunction`` object or function title string.
            arguments: Runtime arguments. The optional ``backend_name`` key is inspected for
                the backend access check but forwarded unchanged.
            config: Optional execution configuration.
            provider: Optional provider name override.
            compute_profile: Optional compute-profile name.
            suppress_low_usage_warning: If ``True``, suppress the warning when remaining runtime
                quota is below ``USAGE_LOW_THRESHOLD_SECONDS``. The exception for exhausted quota
                (at or below ``USAGE_ZERO_EPSILON_SECONDS``) is still raised.

        Returns:
            :class:`~qiskit_serverless.core.job.Job` handle for the submitted run.

        Raises:
            QiskitServerlessException: If quota is exhausted, the backend is inaccessible, or
                the instance has no available backends.
        """
        backend_name = (arguments or {}).get("backend_name")

        self._check_usage(suppress_low_usage_warning)

        if backend_name:
            # Single-backend lookup — fast and confirms access without a full instance listing.
            self.backend(backend_name)
        else:
            # No specific backend requested; verify the instance exposes at least one.
            if not self.backends():
                raise QiskitServerlessException(
                    f"Instance '{self.instance}' has no backends available. "
                    "Cannot run a Qiskit Function without an accessible backend. "
                    "Check your instance configuration at https://quantum.cloud.ibm.com/instances."
                )

        return super().run(
            program=program,
            arguments=arguments,
            config=config,
            provider=provider,
            compute_profile=compute_profile,
        )


def _upload_with_docker_image(  # pylint: disable=too-many-positional-arguments
    program: QiskitFunction,
    url: str,
    token: str,
    span: Any,
    client: RunService,
    instance: Optional[str],
    channel: Optional[str],
) -> RunnableQiskitFunction:
    """Uploads function with custom docker image.

    Args:
        program (QiskitFunction): function instance
        url (str): upload gateway url
        token (str): auth token
        span (Any): tracing span
        instance (Optional[str]): IBM Cloud crn

    Returns:
        str: uploaded function name
    """
    response_data = safe_json_request_as_dict(
        request=lambda: requests.post(
            url=url,
            data={
                "title": program.title,
                "provider": program.provider,
                "image": program.image,
                "runner": program.runner,
                "arguments": json.dumps({}),
                "dependencies": json.dumps(program.dependencies or []),
                "env_vars": json.dumps(program.env_vars or {}),
                "description": program.description,
                "version": program.version,
            },
            headers=get_headers(token=token, instance=instance, channel=channel),
            timeout=REQUESTS_TIMEOUT,
        )
    )
    program_title = response_data.get("title", "na")
    program_provider = response_data.get("provider", "na")
    span.set_attribute("function.title", program_title)
    span.set_attribute("function.provider", program_provider)
    response_data["client"] = client
    return RunnableQiskitFunction.from_json(response_data)


def _upload_with_artifact(  # pylint:  disable=too-many-positional-arguments, too-many-locals
    program: QiskitFunction,
    url: str,
    token: str,
    span: Any,
    client: RunService,
    instance: Optional[str],
    channel: Optional[str],
) -> RunnableQiskitFunction:
    """Uploads function with artifact.

    Args:
        program (QiskitFunction): function instance
        url (str): endpoint for gateway upload
        token (str): auth token
        span (Any): tracing span
        instance (Optional[str]): IBM Cloud crn

    Raises:
        QiskitServerlessException: if no entrypoint or size of artifact is too large.

    Returns:
        str: uploaded function name
    """
    artifact_file_path = os.path.join(program.working_dir, "artifact.tar")

    # check if entrypoint exists
    if not os.path.exists(os.path.join(program.working_dir, program.entrypoint)) or program.entrypoint[0] == "/":
        raise QiskitServerlessException(
            f"Entrypoint file [{program.entrypoint}] does not exist " f"in [{program.working_dir}] working directory."
        )

    try:
        with tarfile.open(artifact_file_path, "w", dereference=True) as tar:
            for filename in os.listdir(program.working_dir):
                fpath = os.path.join(program.working_dir, filename)
                tar.add(fpath, arcname=filename)

        # check file size
        size_in_mb = Path(artifact_file_path).stat().st_size / 1024**2
        if size_in_mb > MAX_ARTIFACT_FILE_SIZE_MB:
            raise QiskitServerlessException(
                f"{artifact_file_path} is {int(size_in_mb)} Mb, "
                f"which is greater than {MAX_ARTIFACT_FILE_SIZE_MB} allowed. "
                f"Try to reduce size of `working_dir`."
            )

        with open(artifact_file_path, "rb") as file:
            response_data = safe_json_request_as_dict(
                request=lambda: requests.post(
                    url=url,
                    data={
                        "title": program.title,
                        "provider": program.provider,
                        "entrypoint": program.entrypoint,
                        "runner": program.runner,
                        "arguments": json.dumps({}),
                        "dependencies": json.dumps(program.dependencies or []),
                        "env_vars": json.dumps(program.env_vars or {}),
                        "description": program.description,
                        "version": program.version,
                    },
                    files={"artifact": file},
                    headers=get_headers(token=token, instance=instance, channel=channel),
                    timeout=REQUESTS_TIMEOUT,
                )
            )
            span.set_attribute("function.title", response_data.get("title", "na"))
            span.set_attribute("function.provider", response_data.get("provider", "na"))
            response_data["client"] = client
            response_function = RunnableQiskitFunction.from_json(response_data)
    except QiskitServerlessException as error:
        raise error
    except Exception as error:  # pylint: disable=broad-exception-caught
        raise QiskitServerlessException from error
    finally:
        if os.path.exists(artifact_file_path):
            os.remove(artifact_file_path)

    return response_function
