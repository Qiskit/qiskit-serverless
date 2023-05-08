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
import json
import logging
import os.path
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

import ray
import requests
from ray.dashboard.modules.job.sdk import JobSubmissionClient

from quantum_serverless.core.constants import (
    RAY_IMAGE,
    REQUESTS_TIMEOUT,
    ENV_GATEWAY_PROVIDER_HOST,
    ENV_GATEWAY_PROVIDER_VERSION,
    GATEWAY_PROVIDER_VERSION_DEFAULT,
)
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


class Provider(JsonSerializable):
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
        return Provider(**dictionary)

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
        if isinstance(other, Provider):
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

    def run_program(
        self, program: Program, arguments: Optional[Dict[str, Any]] = None
    ) -> Job:
        """Execute a program as a async job.

        Example:
            >>> serverless = QuantumServerless()
            >>> program = Program(
            >>>     "job.py",
            >>>     arguments={"arg1": "val1"},
            >>>     dependencies=["requests"]
            >>> )
            >>> job = serverless.run_program(program)
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

        return job_client.run_program(program, arguments)


class KuberayProvider(Provider):
    """Implements CRUD for Kuberay API server."""

    def __init__(
        self,
        name: str,
        host: Optional[str] = None,
        namespace: Optional[str] = "default",
        img: Optional[str] = RAY_IMAGE,
        token: Optional[str] = None,
        compute_resource: Optional[ComputeResource] = None,
        available_compute_resources: Optional[List[ComputeResource]] = None,
    ):
        """Kuberay provider for serverless computation.

        Example:
            >>> provider = Provider(
            >>>    name="<NAME>",
            >>>    host="<HOST>",
            >>>    namespace="<NAMESPACE>",
            >>>    token="<TOKEN>",
            >>>    compute_resource=ComputeResource(
            >>>        name="<COMPUTE_RESOURCE_NAME>",
            >>>        host="<COMPUTE_RESOURCE_HOST>"
            >>>    ),
            >>> )

        Args:
            name: name of provider
            host: host of provider a.k.a managers host
            namespace: namespace to deploy provider in
            image: container image to use for ray cluster
            token: authentication token for manager
            compute_resource: selected compute_resource from provider
            available_compute_resources: available clusters in provider
        """
        super().__init__(name)
        self.name = name
        self.host = host
        self.token = token
        self.namespace = namespace
        self.image = img
        self.compute_resource = compute_resource
        if available_compute_resources is None:
            if compute_resource is not None:
                available_compute_resources = [compute_resource]
            else:
                available_compute_resources = []
        self.available_compute_resources = available_compute_resources
        self.api_root = f"{self.host}/apis/v1alpha2/namespaces/{self.namespace}"

    def get_compute_resources(self) -> List[ComputeResource]:
        """Return compute resources for provider."""
        req = requests.get(self.api_root + "/clusters", timeout=TIMEOUT)
        if req.status_code != 200 or not req.json():
            return []

        clusters = req.json()["clusters"]

        resources = []
        # for each cluster, create a ComputeResource and append it
        for cluster in clusters:
            resource = ComputeResource(name=cluster["name"])
            resources.append(resource)

        return resources

    def create_compute_resource(self, resource) -> int:
        """
        Create compute resource for provider.

        First, create a compute_template based on the defined ComputeResource.
        If the compute_template already exists (which shouldn't be the case,
        exit silently. Otherwise, create the template. This template is
        ephemeral and will be deleted when no longer needed (either the cluster
        was created or we failed to create it and thus need to start over).

        Then use that template to create a KubeRay Cluster. If the cluster
        already exists, we exit silently. Users are only able to configure the
        amount of cpu/memory and the number of worker replicas. The full spec
        can be found in the KubeRay API spec under the "protoCluster"
        definition:
        https://github.com/ray-project/kuberay/blob/master/proto/swagger/cluster.swagger.json
        """
        template_name = self.name + "-template"

        # Create template from resource
        req = requests.get(
            self.api_root + f"/compute_templates/{template_name}",
            timeout=TIMEOUT,
        )
        if req.ok:
            print(f"template name {template_name} already exists")
            return 1

        data = {
            "name": template_name,
            "namespace": self.namespace,
            "cpu": resource.resources["cpu"],
            "memory": resource.resources["memory"],
        }
        req = requests.post(
            self.api_root + "/compute_templates", json=data, timeout=TIMEOUT
        )
        if not req.ok:
            req.raise_for_status()
            return 1

        # Create cluster from template
        req = requests.get(
            self.api_root + f"/clusters/{self.name}",
            timeout=TIMEOUT,
        )
        if req.ok:
            print(f"cluster {self.name} already exists")
            self.delete_kuberay_template(template_name)
            return 1

        data = {
            "name": self.name,
            "namespace": self.namespace,
            "user": "default",
            "clusterSpec": {
                "headGroupSpec": {
                    "computeTemplate": template_name,
                    "image": self.image,
                    "rayStartParams": {
                        "dashboard-host": "127.0.0.1",
                        "metrics-export-port": "8080",
                    },
                    "volumes": [],
                },
            },
            "workerGroupSpec": [
                {
                    "groupName": "default-group",
                    "computeTemplate": template_name,
                    "image": self.image,
                    "replicas": resource.resources["worker_replicas"],
                    "rayStartParams": {
                        "node-ip-address": "$MY_POD_IP",
                    },
                },
            ],
        }
        req = requests.post(
            self.api_root + "/clusters",
            json=data,
            timeout=TIMEOUT,
        )
        if req.status_code != 200:
            self.delete_kuberay_template(template_name)
            req.raise_for_status()
            return 1

        # Delete template
        req = self.delete_kuberay_template(template_name)
        if req.status_code != 200:
            req.raise_for_status()
            return 1

        return 0

    def delete_compute_resource(self, resource) -> int:
        """Delete compute resource for provider."""
        req = requests.delete(
            self.api_root + f"/clusters/{resource}",
            timeout=TIMEOUT,
        )
        if req.status_code != 200:
            req.raise_for_status()
            return 1

        return 0

    def delete_kuberay_template(self, resource):
        """Delete a KubeRay compute template (helper function."""
        return requests.delete(
            self.api_root + f"/compute_templates/{resource}",
            timeout=TIMEOUT,
        )

    def get_jobs(self, **kwargs) -> List[Job]:
        raise NotImplementedError


class GatewayProvider(Provider):
    """GatewayProvider."""

    def __init__(
        self,
        name: Optional[str] = None,
        host: Optional[str] = None,
        version: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
    ):
        """GatewayProvider.

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

        if token is None and (username is None or password is None):
            raise QuantumServerlessException(
                "Authentication credentials must "
                "be provided in form of `username` "
                "and `password` or `token`."
            )

        super().__init__(name)
        self.host = host
        self.version = version
        self._token = token
        if token is None:
            self._fetch_token(username, password)

        self._job_client = GatewayJobClient(self.host, self._token, self.version)

    def get_compute_resources(self) -> List[ComputeResource]:
        raise NotImplementedError("GatewayProvider does not support resources api yet.")

    def create_compute_resource(self, resource) -> int:
        raise NotImplementedError("GatewayProvider does not support resources api yet.")

    def delete_compute_resource(self, resource) -> int:
        raise NotImplementedError("GatewayProvider does not support resources api yet.")

    def get_job_by_id(self, job_id: str) -> Optional[Job]:
        job = None
        url = f"{self.host}/api/{self.version}/jobs/{job_id}/"
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=REQUESTS_TIMEOUT,
        )
        if response.ok:
            data = json.loads(response.text)
            job = Job(
                job_id=data.get("id"),
                job_client=self._job_client,
            )
        else:
            logging.warning(response.text)

        return job

    def run_program(
        self, program: Program, arguments: Optional[Dict[str, Any]] = None
    ) -> Job:
        return self._job_client.run_program(program, arguments)

    def get_jobs(self, **kwargs) -> List[Job]:
        jobs = []
        url = f"{self.host}/api/{self.version}/jobs/"
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=REQUESTS_TIMEOUT,
        )
        if response.ok:
            jobs = [
                Job(
                    job_id=job.get("id"),
                    job_client=self._job_client,
                )
                for job in json.loads(response.text).get("results", [])
            ]
        else:
            logging.warning(response.text)

        return jobs

    def _fetch_token(self, username: str, password: str):
        gateway_response = requests.post(
            url=f"{self.host}/dj-rest-auth/keycloak/login/",
            data={"username": username, "password": password},
            timeout=REQUESTS_TIMEOUT,
        )

        if not gateway_response.ok:
            raise QuantumServerlessException(gateway_response.text)

        gateway_token = json.loads(gateway_response.text).get("access")
        self._token = gateway_token
