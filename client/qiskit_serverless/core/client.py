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

    ComputeResource
    ServerlessClient
"""
# pylint: disable=duplicate-code
import logging
import warnings
import os.path
import os
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Union

import ray
import requests
from ray.dashboard.modules.job.sdk import JobSubmissionClient
from opentelemetry import trace
from qiskit_ibm_runtime import QiskitRuntimeService

from qiskit_serverless.core.constants import (
    REQUESTS_TIMEOUT,
    ENV_GATEWAY_PROVIDER_HOST,
    ENV_GATEWAY_PROVIDER_VERSION,
    ENV_GATEWAY_PROVIDER_TOKEN,
    GATEWAY_PROVIDER_VERSION_DEFAULT,
    IBM_SERVERLESS_HOST_URL,
)
from qiskit_serverless.core.files import GatewayFilesClient
from qiskit_serverless.core.job import (
    Job,
    RayJobClient,
    GatewayJobClient,
    LocalJobClient,
    BaseJobClient,
    Configuration,
)
from qiskit_serverless.core.function import QiskitFunction
from qiskit_serverless.core.tracing import _trace_env_vars
from qiskit_serverless.exception import QiskitServerlessException
from qiskit_serverless.utils import JsonSerializable
from qiskit_serverless.utils.json import safe_json_request
from qiskit_serverless.visualizaiton import Widget

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


class BaseClient(JsonSerializable):
    """
    A client class for specifying custom compute resources.

    Example:
        >>> client = BaseClient(
        >>>    name="<NAME>",
        >>>    host="<HOST>",
        >>>    token="<TOKEN>",
        >>>    compute_resource=ComputeResource(
        >>>        name="<COMPUTE_RESOURCE_NAME>",
        >>>        host="<COMPUTE_RESOURCE_HOST>"
        >>>    ),
        >>> )
    """

    def __init__(  # pylint:  disable=too-many-positional-arguments
        self,
        name: str,
        host: Optional[str] = None,
        token: Optional[str] = None,
        compute_resource: Optional[ComputeResource] = None,
        available_compute_resources: Optional[List[ComputeResource]] = None,
    ):
        """
        Initialize a BaseClient instance.

        Args:
            name: name of client
            host: host of client a.k.a managers host
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
            raise QiskitServerlessException(
                f"ComputeResource was not selected for provider {self.name}"
            )
        return self.compute_resource.context(**kwargs)

    def __eq__(self, other):
        if isinstance(other, BaseProvider):
            return self.name == other.name

        return False

    def __repr__(self):
        return f"<{self.name}>"

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

    def run(
        self,
        program: Union[QiskitFunction, str],
        arguments: Optional[Dict[str, Any]] = None,
        config: Optional[Configuration] = None,
    ) -> Job:
        """Execute a program as a async job.

        Example:
            >>> serverless = QiskitServerless()
            >>> program = QiskitFunction(
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

        return job_client.run(program, None, arguments, config)

    def upload(self, program: QiskitFunction):
        """Uploads program."""
        raise NotImplementedError

    def files(self) -> List[str]:
        """Returns list of available files produced by programs to download."""
        raise NotImplementedError

    def download(
        self,
        file: str,
        download_location: str = "./",
    ):
        """Download file."""
        warnings.warn(
            "`download` method has been deprecated. "
            "And will be removed in future releases. "
            "Please, use `file_download` instead.",
            DeprecationWarning,
        )
        return self.file_download(file, download_location)

    def file_download(
        self,
        file: str,
        target_name: Optional[str] = None,
        download_location: str = "./",
    ):
        """Download file."""
        raise NotImplementedError

    def file_delete(self, file: str):
        """Deletes file uploaded or produced by the programs,"""
        raise NotImplementedError

    def file_upload(self, file: str):
        """Upload file."""
        raise NotImplementedError

    def widget(self):
        """Widget for information about provider and jobs."""
        return Widget(self).show()

    def get_programs(self, **kwargs):
        """[Deprecated] Returns list of available programs."""
        warnings.warn(
            "`get_programs` method has been deprecated. "
            "And will be removed in future releases. "
            "Please, use `list` instead.",
            DeprecationWarning,
        )
        return self.list(**kwargs)

    def list(self, **kwargs) -> List[QiskitFunction]:
        """Returns list of available programs."""
        raise NotImplementedError

    def get(
        self, title: str, provider: Optional[str] = None
    ) -> Optional[QiskitFunction]:
        """Returns qiskit function based on title provided."""
        raise NotImplementedError


class BaseProvider(BaseClient):
    """
    [Deprecated since version 0.10.0] Use :class:`.BaseClient` instead.

    A provider for connecting to a specified host. This class has been
    renamed to :class:`.BaseClient`.
    """


class ServerlessClient(BaseClient):
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
        verbose: bool = False,
    ):
        """
        Initializes the ServerlessClient instance.

        Args:
            name: name of client
            host: host of gateway
            version: version of gateway
            token: authorization token
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

        super().__init__(name)
        self.verbose = verbose
        self.host = host
        self.version = version
        self._verify_token(token)
        self._token = token

        self._job_client = GatewayJobClient(self.host, self._token, self.version)
        self._files_client = GatewayFilesClient(self.host, self._token, self.version)

    def get_compute_resources(self) -> List[ComputeResource]:
        raise NotImplementedError(
            "ServerlessClient does not support resources api yet."
        )

    def create_compute_resource(self, resource) -> int:
        raise NotImplementedError(
            "ServerlessClient does not support resources api yet."
        )

    def delete_compute_resource(self, resource) -> int:
        raise NotImplementedError(
            "ServerlessClient does not support resources api yet."
        )

    def get_job_by_id(self, job_id: str) -> Optional[Job]:
        return self._job_client.get(job_id)

    def run(
        self,
        program: Union[QiskitFunction, str],
        arguments: Optional[Dict[str, Any]] = None,
        config: Optional[Configuration] = None,
    ) -> Job:
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("Provider.run"):
            warnings.warn(
                "`run` method has been deprecated. "
                "And will be removed in future releases. "
                "Please, use `function.run` instead.",
                DeprecationWarning,
            )
            if isinstance(program, QiskitFunction) and program.entrypoint is not None:
                job = self._job_client.run(program.title, None, arguments, config)
            else:
                job = self._job_client.run(program, None, arguments, config)
        return job

    def upload(self, program: QiskitFunction):
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("Provider.upload"):
            response = self._job_client.upload(program)
        return response

    def get_jobs(self, **kwargs) -> List[Job]:
        return self._job_client.list(**kwargs)

    def files(self, provider: Optional[str] = None) -> List[str]:
        return self._files_client.list(provider)

    def file_download(
        self,
        file: str,
        target_name: Optional[str] = None,
        download_location: str = "./",
        provider: Optional[str] = None,
    ):
        return self._files_client.download(
            file, download_location, target_name, provider
        )

    def file_delete(self, file: str, provider: Optional[str] = None):
        return self._files_client.delete(file, provider)

    def file_upload(self, file: str, provider: Optional[str] = None):
        return self._files_client.upload(file, provider)

    def list(self, **kwargs) -> List[QiskitFunction]:
        """Returns list of available programs."""
        return self._job_client.get_programs(**kwargs)

    def get(
        self, title: str, provider: Optional[str] = None
    ) -> Optional[QiskitFunction]:
        return self._job_client.get_program(title=title, provider=provider)

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
        except QiskitServerlessException as reason:
            raise QiskitServerlessException("Cannot verify token.") from reason


class ServerlessProvider(ServerlessClient):
    """
    [Deprecated since version 0.10.0] Use :class:`.ServerlessClient` instead.

    A provider for connecting to a specified host. This class has been
    renamed to :class:`.ServerlessClient`.
    """


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

    def __init__(self, token: Optional[str] = None, name: Optional[str] = None):
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
        """
        token = token or QiskitRuntimeService(name=name).active_account().get("token")
        super().__init__(token=token, host=IBM_SERVERLESS_HOST_URL)

    @staticmethod
    def save_account(
        token: Optional[str] = None,
        name: Optional[str] = None,
        overwrite: Optional[bool] = False,
    ) -> None:
        """
        Save the account to disk for future use.

        Args:
            token: IBM Quantum API token
            name: Name of the account to save
            overwrite: ``True`` if the existing account is to be overwritten
        """
        QiskitRuntimeService.save_account(token=token, name=name, overwrite=overwrite)

    def get_compute_resources(self) -> List[ComputeResource]:
        raise NotImplementedError(
            "IBMServerlessClient does not support resources api yet."
        )

    def create_compute_resource(self, resource) -> int:
        raise NotImplementedError(
            "IBMServerlessClient does not support resources api yet."
        )

    def delete_compute_resource(self, resource) -> int:
        raise NotImplementedError(
            "IBMServerlessClient does not support resources api yet."
        )


class IBMServerlessProvider(IBMServerlessClient):
    """
    [Deprecated since version 0.10.0] Use :class:`.IBMServerlessClient` instead.

    A provider for connecting to IBM Serverless instance. This class has been
    renamed to :class:`.IBMServerlessClient`.
    """


class RayClient(BaseClient):
    """RayClient."""

    def __init__(self, host: str):
        """Ray client

        Args:
            host: ray head node host

        Example:
            >>> ray_provider = RayClient("http://localhost:8265")
        """
        super().__init__("ray-client", host)
        self.client = RayJobClient(JobSubmissionClient(host))

    def run(
        self,
        program: Union[QiskitFunction, str],
        arguments: Optional[Dict[str, Any]] = None,
        config: Optional[Configuration] = None,
    ) -> Job:
        if isinstance(program, str):
            raise NotImplementedError("Ray client only supports full Programs.")

        return self.client.run(program, None, arguments, config)

    def get_job_by_id(self, job_id: str) -> Optional[Job]:
        return self.client.get(job_id)

    def get_jobs(self, **kwargs) -> List[Job]:
        return self.client.list()


class RayProvider(RayClient):
    """
    [Deprecated since version 0.10.0] Use :class:`.RayClient` instead.

    A provider for connecting to a ray head node. This class has been
    renamed to :class:`.RayClient`.
    """


class LocalClient(BaseClient):
    """LocalClient."""

    def __init__(self):
        """Local client

        Args:

        Example:
            >>> local = LocalClient())
        """
        super().__init__("local-client")
        self.client = LocalJobClient()
        self.in_test = os.getenv("IN_TEST")

    def run(
        self,
        program: Union[QiskitFunction, str],
        arguments: Optional[Dict[str, Any]] = None,
        config: Optional[Configuration] = None,
    ) -> Job:
        warnings.warn(
            "`client.run` method has been deprecated. "
            "And will be removed in future releases. "
            "Please, use `function.run` instead.",
            DeprecationWarning,
        )
        if isinstance(program, QiskitFunction) and program.entrypoint is not None:
            job = self.client.run(program.title, None, arguments, config)
        else:
            job = self.client.run(program, None, arguments, config)
        return job

    def get_job_by_id(self, job_id: str) -> Optional[Job]:
        return self.client.get(job_id)

    def get_jobs(self, **kwargs) -> List[Job]:
        return self.client.list()

    def upload(self, program: QiskitFunction):
        return self.client.upload(program)

    def widget(self):
        """Widget for information about provider and jobs."""
        return Widget(self).show()

    def get_programs(self, **kwargs) -> List[QiskitFunction]:
        return self.client.get_programs(**kwargs)

    def files(self) -> List[str]:
        if self.in_test:
            logging.warning("files method is not implemented in LocalProvider.")
            return []
        raise NotImplementedError("files method is not implemented in LocalProvider.")

    def file_upload(self, file: str):
        if self.in_test:
            logging.warning("file_upload method is not implemented in LocalProvider.")
            return
        raise NotImplementedError("files method is not implemented in LocalProvider.")

    def file_download(
        self,
        file: str,
        target_name: Optional[str] = None,
        download_location: str = "./",
    ):
        if self.in_test:
            logging.warning("file_download method is not implemented in LocalProvider.")
            return None
        raise NotImplementedError("files method is not implemented in LocalProvider.")

    def file_delete(self, file: str):
        if self.in_test:
            logging.warning("file_delete method is not implemented in LocalProvider.")
            return None
        raise NotImplementedError("files method is not implemented in LocalProvider.")

    def list(self, **kwargs):
        return self.client.get_programs(**kwargs)

    def get(
        self, title: str, provider: Optional[str] = None
    ) -> Optional[QiskitFunction]:
        functions = {
            function.title: function for function in self.client.get_programs()
        }
        return functions.get(title)


class LocalProvider(LocalClient):
    """
    [Deprecated since version 0.10.0] Use :class:`.LocalClient` instead.

    A provider for connecting to local job execution instance. This class has been
    renamed to :class:`.LocalClient`.
    """
