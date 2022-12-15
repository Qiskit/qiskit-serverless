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
=================================================================
Quantum serverless (:mod:`quantum_serverless.quantum_serverless`)
=================================================================

.. currentmodule:: quantum_serverless.quantum_serverless

Quantum serverless
==================

.. autosummary::
    :toctree: ../stubs/

    QuantumServerless
"""
import json
import logging
import os
import warnings
from typing import Optional, Union, List, Dict, Any
from uuid import uuid4

import requests
from ray._private.worker import BaseContext

from quantum_serverless.core.job import Job, RuntimeEnv
from quantum_serverless.core.program import Program
from quantum_serverless.core.provider import Provider, ComputeResource
from quantum_serverless.exception import QuantumServerlessException

Context = Union[BaseContext]


class QuantumServerless:
    """QuantumServerless class."""

    @classmethod
    def load_configuration(cls, path: str) -> "QuantumServerless":
        """Creates instance from configuration file.

        Example:
            >>> quantum_serverless = QuantumServerless.load_configuration("./my_config.json")

        Args:
            path: path to file with configuration

        Returns:
            Instance of QuantumServerless
        """
        with open(path, "r") as config_file:  # pylint: disable=unspecified-encoding
            config = json.load(config_file)
            return QuantumServerless(config)

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Quantum serverless management class.

        Example:
            >>> configuration = {
            >>>     "providers": [{
            >>>         "name": "my_provider",
            >>>         "compute_resource": {
            >>>             "name": "my_resource",
            >>>             "host": "<HEAD_NODE_HOST>",
            >>>             "port": 10001
            >>>         }
            >>>     }]
            >>> }
            >>> quantum_serverless = QuantumServerless(configuration)
            >>>
            >>> with quantum_serverless.provider("my_provider"):
            >>>     ...

        Example:
            >>> quantum_serverless = QuantumServerless()
            >>>
            >>> with quantum_serverless:
            >>>     ...

        Args:
            config: configuration

        Raises:
            QuantumServerlessException
        """
        self._providers: List[Provider] = load_config(config)
        self._selected_provider: Provider = self._providers[-1]

        self._allocated_context: Optional[Context] = None

    def __enter__(self):
        self._allocated_context = self._selected_provider.context()
        return self._allocated_context

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._allocated_context:
            self._allocated_context.disconnect()
        self._allocated_context = None

    @property
    def job_client(self):
        """Job client for given provider."""
        return self._selected_provider.job_client()

    def run_program(self, program: Program) -> Optional[Job]:
        """Executes program as a async job

        Example:
            >>> serverless = QuantumServerless()
            >>> nested_program = Program(
            >>>     "job.py",
            >>>     arguments={"arg1": "val1"},
            >>>     dependencies=["requests"]
            >>> )
            >>> job = serverless.run_program(nested_program)
            >>> # <Job | ...>

        Args:
            program: program object

        Returns:
            Job
        """
        job_client = self.job_client

        if job_client is None:
            logging.warning(  # pylint: disable=logging-fstring-interpolation
                f"Job has not been submitted as no provider "
                f"with remote host has been configured. "
                f"Selected provider: {self._selected_provider}"
            )
            return None

        arguments = ""
        if program.arguments is not None:
            arg_list = [f"--{key}={value}" for key, value in program.arguments.items()]
            arguments = " ".join(arg_list)
        entrypoint = f"python {program.entrypoint} {arguments}"

        job_id = job_client.submit_job(
            entrypoint=entrypoint,
            submission_id=f"qs_{uuid4()}",
            runtime_env={
                "working_dir": program.working_dir,
                "pip": program.dependencies,
                "env_vars": program.env_vars,
            },
        )
        return Job(job_id=job_id, job_client=job_client)

    def run_job(
        self,
        entrypoint: str,
        runtime_env: Optional[Union[Dict[str, Any], RuntimeEnv]] = None,
    ) -> Optional[Job]:
        """Runs given entrypoint script as job.

        Example:
            >>> job = QuantumServerless(...).run_job(
            >>>     entrypoint="python job.py",
            >>>     runtime_env={
            >>>         "working_dir": "./",
            >>>         # "pip": ["requests==2.26.0"]
            >>>     }
            >>> )
            >>> job.status()
            >>> job.logs()

        Args:
            entrypoint: how to execute your job
            runtime_env: workdir, extra dependencies, etc.

        Returns:
            job
        """
        warnings.warn(
            "Function run_job is deprecated and will be removed in future releases."
            "Please, use run_program instead.",
            DeprecationWarning,
            stacklevel=2,
        )

        job_client = self.job_client

        if job_client is None:
            logging.warning(  # pylint: disable=logging-fstring-interpolation
                f"Job has not been submitted as no provider "
                f"with remote host has been configured. "
                f"Selected provider: {self._selected_provider}"
            )
            return None

        job_id = job_client.submit_job(
            entrypoint=entrypoint,
            submission_id=f"qs_{uuid4()}",
            runtime_env=runtime_env,
        )
        return Job(job_id=job_id, job_client=job_client)

    def get_job_by_id(self, job_id: str) -> Optional[Job]:
        """Returns job by job id.

        Args:
            job_id: job id

        Returns:
            Job instance
        """
        job_client = self.job_client

        if job_client is None:
            logging.warning(  # pylint: disable=logging-fstring-interpolation
                f"Job has not been found as no provider "
                f"with remote host has been configured. "
                f"Selected provider: {self._selected_provider}"
            )
            return None
        job_client.get_job_info(job_id)
        return Job(job_id=job_id, job_client=job_client)

    def provider(
        self,
        provider: Union[str, Provider],
        **kwargs,
    ) -> Context:
        """Sets provider for context allocation.

        Args:
            provider: Provider instance or name of provider
            **kwargs: arguments that will be passed to context initialization.
                See https://docs.ray.io/en/latest/ray-core/package-ref.html#ray-init

        Returns:
            Context
        """
        if isinstance(provider, Provider) and provider.compute_resource is None:
            raise QuantumServerlessException(
                "Given provider does not have compute_resources"
            )

        if isinstance(provider, str):
            available_providers: Dict[str, Provider] = {
                p.name: p for p in self._providers
            }
            if provider in available_providers:
                provider = available_providers[provider]
            else:
                raise QuantumServerlessException(
                    f"Provider {provider} is not in a list of available providers "
                    f"{list(available_providers.keys())}"
                )

        return provider.context(**kwargs)

    def add_provider(self, provider: Provider) -> "QuantumServerless":
        """Adds provider to the list of available providers.

        Args:
            provider: provider instance

        Returns:
            QuantumServerless instance
        """
        self._providers.append(provider)
        return self

    def set_provider(self, provider: Union[str, int, Provider]) -> "QuantumServerless":
        """Set provider for default context allocation.

        Args:
            provider: provider instance

        Returns:
            QuantumServerless instance
        """
        providers = self._providers
        if isinstance(provider, int):
            if len(providers) <= provider:
                raise QuantumServerlessException(
                    f"Selected index is out of bounds. "
                    f"You picked {provider} index whereas only {len(providers)}"
                    f"available"
                )
            self._selected_provider = providers[provider]

        elif isinstance(provider, str):
            provider_names = [c.name for c in providers]
            if provider not in provider_names:
                raise QuantumServerlessException(
                    f"{provider} name is not in a list "
                    f"of available provider names: {provider_names}."
                )
            self._selected_provider = providers[provider_names.index(provider)]

        elif isinstance(provider, Provider):
            self._selected_provider = provider

        return self

    def providers(self) -> List[Provider]:
        """Returns list of available providers.

        Returns:
            list of providers
        """
        return self._providers

    def __repr__(self):
        providers = ", ".join(provider.name for provider in self.providers())
        return f"<QuantumServerless | providers [{providers}]>"


def load_config(config: Optional[Dict[str, Any]] = None) -> List[Provider]:
    """Loads providers from configuration."""
    local_provider = Provider(
        name="local",
        compute_resource=ComputeResource(name="local"),
        available_compute_resources=[ComputeResource(name="local")],
    )
    providers = [local_provider]

    if config is not None:
        for provider_config in config.get("providers", []):
            compute_resource = None
            if provider_config.get("compute_resource"):
                compute_resource = ComputeResource(
                    **provider_config.get("compute_resource")
                )
            # support compute_resource definition
            if provider_config.get("cluster"):
                warnings.warn(
                    "Clusters has been deprecated in favor of compute resources."
                    "Use `compute_resource` instead of `compute_resource`.",
                    DeprecationWarning,
                )
                compute_resource = ComputeResource(
                    **provider_config.get("compute_resource")
                )

            available_compute_resources = []
            if provider_config.get("available_compute_resources"):
                for resource_json in provider_config.get("available_compute_resources"):
                    available_compute_resources.append(ComputeResource(**resource_json))
            providers.append(
                Provider(
                    **{
                        **provider_config,
                        **{
                            "compute_resource": compute_resource,
                            "available_compute_resources": available_compute_resources,
                        },
                    }
                )
            )

    if os.environ.get("QS_CLUSTER_MANAGER_ADDRESS", None):
        auto_discovered_provider = get_auto_discovered_provider(
            manager_address=os.environ.get("QS_CLUSTER_MANAGER_ADDRESS"),
            token=os.environ.get("QS_CLUSTER_MANAGER_TOKEN"),
        )
        if auto_discovered_provider is not None:
            providers.append(auto_discovered_provider)

    return providers


def get_auto_discovered_provider(
    manager_address: str, token: Optional[str] = None
) -> Optional[Provider]:
    """Makes http request to manager to get available clusters."""
    compute_resources = []

    headers = {"Authorization": f"Bearer {token}"} if token else None
    url = f"{manager_address}/quantum-serverless-manager/cluster/"

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.ok:
            names_response = json.loads(response.text)
            for cr_name in names_response:
                name = cr_name.get("name")
                cluster_details_response = requests.get(
                    f"{url}{name}", headers=headers, timeout=10
                )
                if cluster_details_response.ok and name:
                    compute_resources.append(
                        ComputeResource.from_dict(
                            json.loads(cluster_details_response.text)
                        )
                    )
        else:
            logging.warning(
                "Something went wrong when trying to connect to provider: [%d] %s",
                response.status_code,
                response.text,
            )

    except Exception:  # pylint: disable=broad-except
        logging.info(
            "Autodiscovery: was not able to autodiscover additional resources."
        )

    if len(compute_resources) > 0:
        return Provider(
            name="auto_discovered",
            compute_resource=compute_resources[0],
            available_compute_resources=compute_resources,
        )

    return None
