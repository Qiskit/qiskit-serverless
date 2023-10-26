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
import os
import json
import logging
import warnings
from typing import Optional, Union, List, Dict, Any

import requests
from ray._private.worker import BaseContext

from opentelemetry import trace  # pylint: disable=duplicate-code
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

from quantum_serverless.core.job import Job
from quantum_serverless.core.program import Program
from quantum_serverless.core.provider import BaseProvider, ComputeResource
from quantum_serverless.exception import QuantumServerlessException

Context = Union[BaseContext]


class QuantumServerless:
    """QuantumServerless class."""

    def __init__(
        self, providers: Optional[Union[BaseProvider, List[BaseProvider]]] = None
    ):
        """Quantum serverless management class.

        Args:
            config: configuration

        Raises:
            QuantumServerlessException
        """
        warnings.warn(
            "The `QuantumServerless` class is deprecated. "
            "Use the identical ServerlessProvider class instead."
        )

        if providers is None:
            providers = [
                BaseProvider("local", compute_resource=ComputeResource(name="local"))
            ]
        elif isinstance(providers, BaseProvider):
            providers = [providers]
        self._providers: List[BaseProvider] = providers
        self._selected_provider: BaseProvider = self._providers[-1]

        self._allocated_context: Optional[Context] = None
        RequestsInstrumentor().instrument()
        resource = Resource(attributes={SERVICE_NAME: "QuantumServerless"})
        provider = TracerProvider(resource=resource)
        otel_exporter = BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=os.environ.get(
                    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://otel-collector:4317"
                ),
                insecure=bool(
                    int(os.environ.get("OTEL_EXPORTER_OTLP_TRACES_INSECURE", "0"))
                ),
            )
        )
        provider.add_span_processor(otel_exporter)
        if bool(int(os.environ.get("OTEL_ENABLED", "0"))):
            trace._set_tracer_provider(
                provider, log=False
            )  # pylint: disable=protected-access

    @property
    def job_client(self):
        """Job client for given provider."""
        return self._selected_provider.job_client()

    def run(
        self, program: Program, arguments: Optional[Dict[str, Any]] = None
    ) -> Optional[Job]:
        """Execute a program as a async job

        Example:
            >>> serverless = QuantumServerless()
            >>> program = Program(
            >>>     "job.py",
            >>>     dependencies=["requests"]
            >>> )
            >>> job = serverless.run(program, {"arg1": 1})
            >>> # <Job | ...>

        Args:
            arguments: arguments to run program with
            program: Program object

        Returns:
            Job
        """
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("QuantumServerless.run"):
            job = self._selected_provider.run(program, arguments)
        return job

    def upload(self, program: Program):
        """Uploads program.

        Args:
            program: Program

        Returns:
            program title
        """
        return self._selected_provider.upload(program)

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

    def files(self):
        """Returns list of available files to download.

        Example:
            >>> serverless = QuantumServerless()
            >>> serverless.files()

        Returns:
            list of available files
        """
        return self._selected_provider.files()

    def file_download(self, file: str, download_location: str = "./"):
        """Downloads file.
        Note: file will be saved with different name to avoid conflicts
              and this name will be returned.

        Example:
            >>> serverless = QuantumServerless()
            >>> serverless.file_download('artifact.tar', directory="./")

        Args:
            file: name of file to download
            download_location: destination directory. Default: current directory
        """
        return self._selected_provider.file_download(file, download_location)

    def file_delete(self, file: str):
        """Deletes file uploaded or produced by the programs.

        Example:
            >>> serverless = QuantumServerless()
            >>> serverless.file_delete('artifact.tar')

        Args:
            file: name of file to delete
        """
        return self._selected_provider.file_delete(file)

    def file_upload(self, file: str):
        """Downloads file.

        Example:
            >>> serverless = QuantumServerless()
            >>> serverless.file_upload('artifact.tar')

        Args:
            file: name of file (with path)  to upload
        """
        return self._selected_provider.file_upload(file)

    def get_programs(self, **kwargs):
        """Get list of available programs.

        Args:
            **kwargs: filtering options

        Returns:
            List of programs.
        """
        return self._selected_provider.get_programs(**kwargs)

    def context(
        self,
        provider: Optional[Union[str, BaseProvider]] = None,
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
            if isinstance(provider, BaseProvider) and provider.compute_resource is None:
                raise QuantumServerlessException(
                    "Given provider does not have compute_resources"
                )

            if isinstance(provider, str):
                available_providers: Dict[str, BaseProvider] = {
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
        provider: Union[str, BaseProvider],
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

    def add_provider(self, provider: BaseProvider) -> "QuantumServerless":
        """Adds provider to the list of available providers.

        Args:
            provider: provider instance

        Returns:
            QuantumServerless instance
        """
        self._providers.append(provider)
        return self

    def set_provider(
        self, provider: Union[str, int, BaseProvider]
    ) -> "QuantumServerless":
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

        elif isinstance(provider, BaseProvider):
            self._selected_provider = provider

        return self

    def providers(self) -> List[BaseProvider]:
        """Returns list of available providers.

        Returns:
            list of providers
        """
        return self._providers

    def widget(self):
        """Widget for information about provider and jobs."""
        return self._selected_provider.widget()

    def __repr__(self):
        providers = ", ".join(provider.name for provider in self.providers())
        return f"<QuantumServerless | providers [{providers}]>"


def get_auto_discovered_provider(
    manager_address: str, token: Optional[str] = None
) -> Optional[BaseProvider]:
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
        return BaseProvider(
            name="auto_discovered",
            compute_resource=compute_resources[0],
            available_compute_resources=compute_resources,
        )

    return None
