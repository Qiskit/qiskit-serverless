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
# pylint: disable=duplicate-code
import json
import os.path
import os
import re
import tarfile
from pathlib import Path
from dataclasses import asdict
from typing import Optional, List, Dict, Any, Union

import requests
from opentelemetry import trace
from qiskit_ibm_runtime import QiskitRuntimeService

from qiskit_serverless.core.constants import (
    REQUESTS_TIMEOUT,
    ENV_GATEWAY_PROVIDER_HOST,
    ENV_GATEWAY_PROVIDER_VERSION,
    ENV_GATEWAY_PROVIDER_TOKEN,
    GATEWAY_PROVIDER_VERSION_DEFAULT,
    IBM_SERVERLESS_HOST_URL,
    MAX_ARTIFACT_FILE_SIZE_MB,
)
from qiskit_serverless.core.client import BaseClient
from qiskit_serverless.core.decorators import trace_decorator_factory
from qiskit_serverless.core.enums import Channel
from qiskit_serverless.core.files import GatewayFilesClient
from qiskit_serverless.core.job import (
    Job,
    Configuration,
)
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
        >>> )
    """

    def __init__(  # pylint:  disable=too-many-positional-arguments
        self,
        name: Optional[str] = None,
        host: Optional[str] = None,
        version: Optional[str] = None,
        token: Optional[str] = None,
        instance: Optional[str] = None,
        channel: str = Channel.IBM_QUANTUM.value,
        verbose: bool = False,
    ):
        """
        Initializes the ServerlessClient instance.

        Args:
            name: name of client
            host: host of gateway
            version: version of gateway
            token: authorization token
            instance: IBM Cloud CRN
            channel: identifies the method to use to authenticate the user
        """
        name = name or "gateway-client"
        host = host or os.environ.get(ENV_GATEWAY_PROVIDER_HOST)
        if host is None:
            raise QiskitServerlessException("Please provide `host` of gateway.")

        version = version or os.environ.get(ENV_GATEWAY_PROVIDER_VERSION)
        if version is None:
            version = GATEWAY_PROVIDER_VERSION_DEFAULT

        token = token or os.environ.get(ENV_GATEWAY_PROVIDER_TOKEN)
        if token is None:
            raise QiskitServerlessException(
                "Authentication credentials must be provided in form of `token`."
            )

        try:
            channel_enum = Channel(channel)
        except ValueError as error:
            raise QiskitServerlessException(
                "Your channel value is not correct. Use one of the available channels: "
                f"{Channel.LOCAL.value}, {Channel.IBM_QUANTUM.value}, {Channel.IBM_CLOUD.value}"
            ) from error

        if channel_enum is Channel.IBM_CLOUD and instance is None:
            raise QiskitServerlessException(
                "Authentication with IBM Cloud requires to pass the CRN as an instance."
            )

        super().__init__(name, host, token, instance)
        self.verbose = verbose
        self.version = version
        self._verify_credentials()

        self._files_client = GatewayFilesClient(
            self.host, self.token, self.version, self.instance
        )

    @classmethod
    def from_dict(cls, dictionary: dict):
        return ServerlessClient(**dictionary)

    def _verify_credentials(self):
        """Verify against the API that the credentials are correct."""
        try:
            safe_json_request(
                request=lambda: requests.get(
                    url=f"{self.host}/api/v1/programs/",
                    headers=get_headers(token=self.token, instance=self.instance),
                    timeout=REQUESTS_TIMEOUT,
                ),
                verbose=self.verbose,
            )
        except QiskitServerlessException as reason:
            raise QiskitServerlessException(
                "Credentials couldn't be verified."
            ) from reason

    ####################
    ####### JOBS #######
    ####################

    @_trace_job("list")
    def jobs(self, **kwargs) -> List[Job]:
        limit = kwargs.get("limit", 10)
        kwargs["limit"] = limit
        offset = kwargs.get("offset", 0)
        kwargs["offset"] = offset

        response_data = safe_json_request_as_dict(
            request=lambda: requests.get(
                f"{self.host}/api/{self.version}/jobs/",
                params=kwargs,
                headers=get_headers(token=self.token, instance=self.instance),
                timeout=REQUESTS_TIMEOUT,
            )
        )

        return [
            Job(job.get("id"), job_service=self, raw_data=job)
            for job in response_data.get("results", [])
        ]

    @_trace_job("provider_list")
    def provider_jobs(self, function: QiskitFunction, **kwargs) -> List[Job]:
        """List of jobs created in this provider and function.

        Args:
            function: QiskitFunction
            **kwargs: additional parameters for the request

        Raises:
            QiskitServerlessException: validation exception

        Returns:
            [Job] : list of jobs
        """

        if not function.provider:
            raise QiskitServerlessException("`function` doesn't have a provider.")

        limit = kwargs.get("limit", 10)
        kwargs["limit"] = limit
        offset = kwargs.get("offset", 0)
        kwargs["offset"] = offset
        kwargs["function"] = function.title
        kwargs["provider"] = function.provider

        response_data = safe_json_request_as_dict(
            request=lambda: requests.get(
                f"{self.host}/api/{self.version}/jobs/provider/",
                params=kwargs,
                headers=get_headers(token=self.token, instance=self.instance),
                timeout=REQUESTS_TIMEOUT,
            )
        )

        return [
            Job(job.get("id"), job_service=self, raw_data=job)
            for job in response_data.get("results", [])
        ]

    @_trace_job("get")
    def job(self, job_id: str) -> Optional[Job]:
        url = f"{self.host}/api/{self.version}/jobs/{job_id}/"
        response_data = safe_json_request_as_dict(
            request=lambda: requests.get(
                url,
                headers=get_headers(token=self.token, instance=self.instance),
                timeout=REQUESTS_TIMEOUT,
            )
        )

        job = None
        job_id = response_data.get("id")
        if job_id is not None:
            job = Job(
                job_id=job_id,
                job_service=self,
            )

        return job

    def run(
        self,
        program: Union[QiskitFunction, str],
        arguments: Optional[Dict[str, Any]] = None,
        config: Optional[Configuration] = None,
        provider: Optional[str] = None,
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
                    headers=get_headers(token=self.token, instance=self.instance),
                    timeout=REQUESTS_TIMEOUT,
                )
            )
            job_id = response_data.get("id")
            span.set_attribute("job.id", job_id)

        return Job(job_id, job_service=self)

    @_trace_job
    def status(self, job_id: str):
        default_status = "Unknown"
        response_data = safe_json_request_as_dict(
            request=lambda: requests.get(
                f"{self.host}/api/{self.version}/jobs/{job_id}/",
                params={"with_result": "false"},
                headers=get_headers(token=self.token, instance=self.instance),
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
        if service:
            data = {
                "service": json.dumps(service, cls=QiskitObjectsEncoder),
            }
        else:
            data = {
                "service": None,
            }
        response_data = safe_json_request_as_dict(
            request=lambda: requests.post(
                f"{self.host}/api/{self.version}/jobs/{job_id}/stop/",
                headers=get_headers(token=self.token, instance=self.instance),
                timeout=REQUESTS_TIMEOUT,
                json=data,
            )
        )

        return response_data.get("message")

    @_trace_job
    def result(self, job_id: str):
        response_data = safe_json_request_as_dict(
            request=lambda: requests.get(
                f"{self.host}/api/{self.version}/jobs/{job_id}/",
                headers=get_headers(token=self.token, instance=self.instance),
                timeout=REQUESTS_TIMEOUT,
            )
        )
        return json.loads(
            response_data.get("result", "{}") or "{}", cls=QiskitObjectsDecoder
        )

    @_trace_job
    def logs(self, job_id: str):
        response_data = safe_json_request_as_dict(
            request=lambda: requests.get(
                f"{self.host}/api/{self.version}/jobs/{job_id}/logs/",
                headers=get_headers(token=self.token, instance=self.instance),
                timeout=REQUESTS_TIMEOUT,
            )
        )
        return response_data.get("logs")

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

    #########################
    ####### Functions #######
    #########################

    def upload(self, program: QiskitFunction) -> Optional[RunnableQiskitFunction]:
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("function.upload") as span:
            span.set_attribute("function", program.title)
            url = f"{self.host}/api/{self.version}/programs/upload/"

            if program.image is not None:
                # upload function with custom image
                function_uploaded = _upload_with_docker_image(
                    program=program,
                    url=url,
                    token=self.token,
                    span=span,
                    client=self,
                    instance=self.instance,
                )
            elif program.entrypoint is not None:
                # upload funciton with artifact
                function_uploaded = _upload_with_artifact(
                    program=program,
                    url=url,
                    token=self.token,
                    span=span,
                    client=self,
                    instance=self.instance,
                )
            else:
                raise QiskitServerlessException(
                    "Function must either have `entrypoint` or `image` specified."
                )

        return function_uploaded

    @_trace_functions("list")
    def functions(self, **kwargs) -> List[RunnableQiskitFunction]:
        """Returns list of available functions."""
        response_data = safe_json_request_as_list(
            request=lambda: requests.get(
                f"{self.host}/api/{self.version}/programs",
                headers=get_headers(token=self.token, instance=self.instance),
                params=kwargs,
                timeout=REQUESTS_TIMEOUT,
            )
        )

        for program_data in response_data:
            program_data["client"] = self

        return [
            RunnableQiskitFunction.from_json(program_data)
            for program_data in response_data
        ]

    @_trace_functions("get_by_title")
    def function(
        self, title: str, provider: Optional[str] = None
    ) -> Optional[RunnableQiskitFunction]:
        """Returns program based on parameters."""
        provider, title = format_provider_name_and_title(
            request_provider=provider, title=title
        )

        response_data = safe_json_request_as_dict(
            request=lambda: requests.get(
                f"{self.host}/api/{self.version}/programs/get_by_title/{title}",
                headers=get_headers(token=self.token, instance=self.instance),
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
        return self._files_client.download(
            file, download_location, function, target_name
        )

    def provider_file_download(
        self,
        file: str,
        function: QiskitFunction,
        target_name: Optional[str] = None,
        download_location: str = "./",
    ):
        """Download a file available to the provider for the specific Qiskit Function."""
        return self._files_client.provider_download(
            file, download_location, function, target_name
        )

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
        IBMServerlessClient.save_account(token=<INSERT_IBM_QUANTUM_TOKEN>)

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
        client = IBMServerlessClient(token=<INSERT_IBM_QUANTUM_TOKEN>)
    """

    def __init__(
        self,
        token: Optional[str] = None,
        name: Optional[str] = None,
        instance: Optional[str] = None,
        channel: str = Channel.IBM_QUANTUM.value,
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
            token: IBM quantum token
            name: Name of the account to load
            instance: IBM Cloud CRN
            channel: identifies the method to use to authenticate the user
        """
        token = token or QiskitRuntimeService(name=name).active_account().get("token")
        super().__init__(
            channel=channel,
            token=token,
            instance=instance,
            host=IBM_SERVERLESS_HOST_URL,
        )

    @staticmethod
    def save_account(
        token: Optional[str] = None,
        name: Optional[str] = None,
        overwrite: Optional[bool] = False,
        instance: Optional[str] = None,
        channel: str = Channel.IBM_QUANTUM.value,
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
        QiskitRuntimeService.save_account(
            token=token,
            name=name,
            overwrite=overwrite,
            instance=instance,
            channel=channel,
        )


def _upload_with_docker_image(  # pylint: disable=too-many-positional-arguments
    program: QiskitFunction,
    url: str,
    token: str,
    span: Any,
    client: RunService,
    instance: Optional[str],
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
                "arguments": json.dumps({}),
                "dependencies": json.dumps(program.dependencies or []),
                "env_vars": json.dumps(program.env_vars or {}),
                "description": program.description,
            },
            headers=get_headers(token=token, instance=instance),
            timeout=REQUESTS_TIMEOUT,
        )
    )
    program_title = response_data.get("title", "na")
    program_provider = response_data.get("provider", "na")
    span.set_attribute("function.title", program_title)
    span.set_attribute("function.provider", program_provider)
    response_data["client"] = client
    return RunnableQiskitFunction.from_json(response_data)


def _upload_with_artifact(  # pylint:  disable=too-many-positional-arguments
    program: QiskitFunction,
    url: str,
    token: str,
    span: Any,
    client: RunService,
    instance: Optional[str],
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
    if (
        not os.path.exists(os.path.join(program.working_dir, program.entrypoint))
        or program.entrypoint[0] == "/"
    ):
        raise QiskitServerlessException(
            f"Entrypoint file [{program.entrypoint}] does not exist "
            f"in [{program.working_dir}] working directory."
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
                        "arguments": json.dumps({}),
                        "dependencies": json.dumps(program.dependencies or []),
                        "env_vars": json.dumps(program.env_vars or {}),
                        "description": program.description,
                    },
                    files={"artifact": file},
                    headers=get_headers(token=token, instance=instance),
                    timeout=REQUESTS_TIMEOUT,
                )
            )
            span.set_attribute("function.title", response_data.get("title", "na"))
            span.set_attribute("function.provider", response_data.get("provider", "na"))
            response_data["client"] = client
            response_function = RunnableQiskitFunction.from_json(response_data)
    except Exception as error:  # pylint: disable=broad-exception-caught
        raise QiskitServerlessException from error
    finally:
        if os.path.exists(artifact_file_path):
            os.remove(artifact_file_path)

    return response_function
