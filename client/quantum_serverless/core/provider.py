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
==================================================
Provider (:mod:`quantum_serverless.core.provider`)
==================================================

.. currentmodule:: quantum_serverless.core.provider

Quantum serverless provider
===========================

.. autosummary::
    :toctree: ../stubs/

    ComputeResource
    Provider
"""
import logging
import os.path
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

import ray
import requests
from ray.dashboard.modules.job.sdk import JobSubmissionClient

from opentelemetry import trace

from quantum_serverless.core.constants import (
    REQUESTS_TIMEOUT,
    ENV_GATEWAY_PROVIDER_HOST,
    ENV_GATEWAY_PROVIDER_VERSION,
    ENV_GATEWAY_PROVIDER_TOKEN,
    GATEWAY_PROVIDER_VERSION_DEFAULT,
    IBM_SERVERLESS_HOST_URL,
)
from quantum_serverless.core.files import GatewayFilesClient
from quantum_serverless.core.job import (
    Job,
    RayJobClient,
    GatewayJobClient,
    BaseJobClient,
)
from quantum_serverless.core.program import Program
from quantum_serverless.core.tracing import _trace_env_vars
from quantum_serverless.exception import QuantumServerlessException
from quantum_serverless.utils import JsonSerializable
from quantum_serverless.utils.json import safe_json_request
from quantum_serverless.visualizaiton import Widget

TIMEOUT = 30


@dataclass
class ComputeResource:
    """ComputeResource class.

    Args:
        name: name of compute_resource
        host: host address of compute_resource
        namespace: k8s namespace of compute_resource
        port_interactive: port of compute_resource for interactive mode
        port_job_server: port of compute resource for job server
        resources: list of resources
    """

    name: str
    host: Optional[str] = None
    port_interactive: int = 10001
    port_job_server: int = 8265
    resources: Optional[Dict[str, float]] = None

    def job_client(self) -> Optional[BaseJobClient]:
        """Return job client for given compute resource.

        Returns:
            job client
        """
        if self.host is not None:
            connection_url = f"http://{self.host}:{self.port_job_server}"
            client = None
            try:
                client = RayJobClient(JobSubmissionClient(connection_url))
            except ConnectionError:
                logging.warning(
                    "Failed to establish connection with jobs server at %s. "
                    "You will not be able to run jobs on this provider.",
                    connection_url,
                )

            return client
        return None

    def context(self, **kwargs):
        """Return context allocated for this compute_resource."""
        _trace_env_vars({}, location="on context allocation")

        init_args = {
            **kwargs,
            **{
                "address": kwargs.get(
                    "address",
                    self.connection_string_interactive_mode(),
                ),
                "ignore_reinit_error": kwargs.get("ignore_reinit_error", True),
                "logging_level": kwargs.get("logging_level", "warning"),
                "resources": kwargs.get("resources", self.resources),
            },
        }

        return ray.init(**init_args)

    def connection_string_interactive_mode(self) -> Optional[str]:
        """Return connection string to compute_resource."""
        if self.host is not None:
            return f"ray://{self.host}:{self.port_interactive}"
        return None

    @classmethod
    def from_dict(cls, data: dict):
        """Create compute_resource object form dict."""
        return ComputeResource(
            name=data.get("name"),
            host=data.get("host"),
            port_interactive=data.get("port_interactive"),
            port_job_server=data.get("port_job_server"),
        )

    def __eq__(self, other: object):
        if isinstance(other, ComputeResource):
            return self.name == other.name and self.host == other.host
        return False

    def __repr__(self):
        return f"<ComputeResource: {self.name}>"


class BaseProvider(JsonSerializable):
    """Provider."""

    def __init__(
        self,
        name: str,
        host: Optional[str] = None,
        token: Optional[str] = None,
        compute_resource: Optional[ComputeResource] = None,
        available_compute_resources: Optional[List[ComputeResource]] = None,
    ):
        """Provider for serverless computation.

        Example:
            >>> provider = Provider(
            >>>    name="<NAME>",
            >>>    host="<HOST>",
            >>>    token="<TOKEN>",
            >>>    compute_resource=ComputeResource(
            >>>        name="<COMPUTE_RESOURCE_NAME>",
            >>>        host="<COMPUTE_RESOURCE_HOST>"
            >>>    ),
            >>> )

        Args:
            name: name of provider
            host: host of provider a.k.a managers host
            token: authentication token for manager
            compute_resource: selected compute_resource from provider
            available_compute_resources: available clusters in provider
        """
        self.name = name
        self.host = host
        self.token = token
        self.compute_resource = compute_resource
        if available_compute_resources is None:
            if compute_resource is not None:
                available_compute_resources = [compute_resource]
            else:
                available_compute_resources = []
        self.available_compute_resources = available_compute_resources

    @classmethod
    def from_dict(cls, dictionary: dict):
        return BaseProvider(**dictionary)

    def job_client(self):
        """Return job client for configured compute resource of provider.

        Returns:
            job client
        """
        return self.compute_resource.job_client()

    def context(self, **kwargs):
        """Allocated context for selected compute_resource for provider."""
        if self.compute_resource is None:
            raise QuantumServerlessException(
                f"ComputeResource was not selected for provider {self.name}"
            )
        return self.compute_resource.context(**kwargs)

    def __eq__(self, other):
        if isinstance(other, BaseProvider):
            return self.name == other.name

        return False

    def __repr__(self):
        return f"<Provider: {self.name}>"

    def get_compute_resources(self) -> List[ComputeResource]:
        """Return compute resources for provider."""
        raise NotImplementedError

    def create_compute_resource(self, resource) -> int:
        """Create compute resource for provider."""
        raise NotImplementedError

    def delete_compute_resource(self, resource) -> int:
        """Delete compute resource for provider."""
        raise NotImplementedError

    def get_jobs(self, **kwargs) -> List[Job]:
        """Return list of jobs.

        Returns:
            list of jobs.
        """
        raise NotImplementedError

    def get_job_by_id(self, job_id: str) -> Optional[Job]:
        """Returns job by job id.

        Args:
            job_id: job id

        Returns:
            Job instance
        """
        job_client = self.job_client()

        if job_client is None:
            logging.warning(  # pylint: disable=logging-fstring-interpolation
                "Job has not been found as no provider "
                "with remote host has been configured. "
            )
            return None
        return Job(job_id=job_id, job_client=job_client)

    def run(self, program: Program, arguments: Optional[Dict[str, Any]] = None) -> Job:
        """Execute a program as a async job.

        Example:
            >>> serverless = QuantumServerless()
            >>> program = Program(
            >>>     "job.py",
            >>>     arguments={"arg1": "val1"},
            >>>     dependencies=["requests"]
            >>> )
            >>> job = serverless.run(program)
            >>> # <Job | ...>

        Args:
            arguments: arguments to run program with
            program: Program object

        Returns:
            Job
        """
        job_client = self.job_client()

        if job_client is None:
            logging.warning(  # pylint: disable=logging-fstring-interpolation
                f"Job has not been submitted as no provider "
                f"with remote host has been configured. "
                f"Selected provider: {self}"
            )
            return None

        return job_client.run(program, arguments)

    def files(self) -> List[str]:
        """Returns list of available files produced by programs to download."""
        raise NotImplementedError

    def download(self, file: str, download_location: str):
        """Download file."""
        raise NotImplementedError

    def delete(self, file: str):
        """Deletes file uploaded or produced by the programs,"""

    def upload(self, file: str):
        """Upload file."""
        raise NotImplementedError

    def widget(self):
        """Widget for information about provider and jobs."""
        return Widget(self).show()


class Provider(BaseProvider):
    """Provider."""

    def __init__(
        self,
        name: Optional[str] = None,
        host: Optional[str] = None,
        version: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
        verbose: bool = False,
    ):
        """Provider.

        Args:
            name: name of provider
            host: host of gateway
            version: version of gateway
            username: username
            password: password
            token: authorization token
        """
        name = name or "gateway-provider"

        host = host or os.environ.get(ENV_GATEWAY_PROVIDER_HOST)
        if host is None:
            raise QuantumServerlessException("Please provide `host` of gateway.")

        version = version or os.environ.get(ENV_GATEWAY_PROVIDER_VERSION)
        if version is None:
            version = GATEWAY_PROVIDER_VERSION_DEFAULT

        token = token or os.environ.get(ENV_GATEWAY_PROVIDER_TOKEN)
        if token is None and (username is None or password is None):
            raise QuantumServerlessException(
                "Authentication credentials must "
                "be provided in form of `username` "
                "and `password` or `token`."
            )

        super().__init__(name)
        self.verbose = verbose
        self.host = host
        self.version = version
        if token is not None:
            self._verify_token(token)
        self._token = token
        if token is None:
            self._fetch_token(username, password)

        self._job_client = GatewayJobClient(self.host, self._token, self.version)
        self._files_client = GatewayFilesClient(self.host, self._token, self.version)

    def get_compute_resources(self) -> List[ComputeResource]:
        raise NotImplementedError("GatewayProvider does not support resources api yet.")

    def create_compute_resource(self, resource) -> int:
        raise NotImplementedError("GatewayProvider does not support resources api yet.")

    def delete_compute_resource(self, resource) -> int:
        raise NotImplementedError("GatewayProvider does not support resources api yet.")

    def get_job_by_id(self, job_id: str) -> Optional[Job]:
        return self._job_client.get(job_id)

    def run(self, program: Program, arguments: Optional[Dict[str, Any]] = None) -> Job:
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("Provider.run"):
            job = self._job_client.run(program, arguments)
        return job

    def get_jobs(self, **kwargs) -> List[Job]:
        return self._job_client.list(**kwargs)

    def files(self) -> List[str]:
        return self._files_client.list()

    def download(self, file: str, download_location: str = "./"):
        return self._files_client.download(file, download_location)

    def delete(self, file: str):
        return self._files_client.delete(file)

    def upload(self, file: str):
        return self._files_client.upload(file)

    def _fetch_token(self, username: str, password: str):
        response_data = safe_json_request(
            request=lambda: requests.post(
                url=f"{self.host}/dj-rest-auth/keycloak/login/",
                data={"username": username, "password": password},
                timeout=REQUESTS_TIMEOUT,
            ),
            verbose=self.verbose,
        )

        self._token = response_data.get("access")

    def _verify_token(self, token: str):
        """Verify token."""
        try:
            safe_json_request(
                request=lambda: requests.get(
                    url=f"{self.host}/api/v1/programs/",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=REQUESTS_TIMEOUT,
                ),
                verbose=self.verbose,
            )
        except QuantumServerlessException as reason:
            raise QuantumServerlessException("Cannot verify token.") from reason


class IBMServerlessProvider(Provider):
    """IBMServerlessProvider."""

    def __init__(self, token: str):
        """Constructor for IBMServerlessProvider

        Args:
            token: IBM quantum token
        """
        super().__init__(token=token, host=IBM_SERVERLESS_HOST_URL)

    def get_compute_resources(self) -> List[ComputeResource]:
        raise NotImplementedError("GatewayProvider does not support resources api yet.")

    def create_compute_resource(self, resource) -> int:
        raise NotImplementedError("GatewayProvider does not support resources api yet.")

    def delete_compute_resource(self, resource) -> int:
        raise NotImplementedError("GatewayProvider does not support resources api yet.")
