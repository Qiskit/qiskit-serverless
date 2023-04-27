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

import requests
from ray._private.worker import BaseContext

from quantum_serverless.core.job import Job
from quantum_serverless.core.program import Program
from quantum_serverless.core.provider import Provider, ComputeResource
from quantum_serverless.exception import QuantumServerlessException

Context = Union[BaseContext]


class QuantumServerless:
    """QuantumServerless class."""

    def __init__(self, providers: Optional[Union[Provider, List[Provider]]] = None):
        """Quantum serverless management class.

        Args:
            config: configuration

        Raises:
            QuantumServerlessException
        """
        if providers is None:
            providers = [
                Provider("local", compute_resource=ComputeResource(name="local"))
            ]
        elif isinstance(providers, Provider):
            providers = [providers]
        self._providers: List[Provider] = providers
        self._selected_provider: Provider = self._providers[-1]

        self._allocated_context: Optional[Context] = None

    def __enter__(self):
        warnings.warn(
            "Calling `with serverless: ...` is deprecated. "
            "Please, consider using `with serverless.context(): ...`",
            DeprecationWarning,
            stacklevel=2,
        )
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

    def run_program(
        self, program: Program, arguments: Optional[Dict[str, Any]] = None
    ) -> Optional[Job]:
        """Execute a program as a async job

        Example:
            >>> serverless = QuantumServerless()
            >>> program = Program(
            >>>     "job.py",
            >>>     dependencies=["requests"]
            >>> )
            >>> job = serverless.run_program(program, {"arg1": 1})
            >>> # <Job | ...>

        Args:
            arguments: arguments to run program with
            program: Program object

        Returns:
            Job
        """
        if program.arguments is not None:
            arguments = program.arguments
        return self._selected_provider.run_program(program, arguments)

    def get_job_by_id(self, job_id: str) -> Optional[Job]:
        """Returns job by job id.

        Args:
            job_id: job id

        Returns:
            Job instance
        """
        return self._selected_provider.get_job_by_id(job_id)

    def get_jobs(self, **kwargs):
        """Return jobs.

        Args:
            **kwargs: filters

        Returns:
            list of jobs
        """
        return self._selected_provider.get_jobs(**kwargs)

    def context(
        self,
        provider: Optional[Union[str, Provider]] = None,
        **kwargs,
    ):
        """Sets context for allocation

        Args:
            provider: Provider instance or name of provider
            **kwargs: arguments that will be passed to context initialization.
                See https://docs.ray.io/en/latest/ray-core/package-ref.html#ray-init

        Returns:
            Context
        """
        if provider is not None:
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
        else:
            provider = self._selected_provider

        return provider.context(**kwargs)

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
        return self.context(provider=provider, **kwargs)

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
