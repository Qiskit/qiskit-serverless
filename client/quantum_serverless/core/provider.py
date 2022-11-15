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

    Cluster
    Provider
"""

from dataclasses import dataclass
from typing import Optional, List, Dict

import ray
from ray.dashboard.modules.job.sdk import JobSubmissionClient

from quantum_serverless.exception import QuantumServerlessException
from quantum_serverless.utils import JsonSerializable


@dataclass
class Cluster:
    """Cluster class.

    Args:
        name: name of cluster
        host: host address of cluster
        port: port of cluster
        ip_address: ip address of cluster
        resources: list of resources
    """

    name: str
    host: Optional[str] = None
    port: Optional[int] = None
    ip_address: Optional[str] = None
    resources: Optional[Dict[str, float]] = None

    def job_client(self) -> Optional[JobSubmissionClient]:
        """Returns job client for given compute resource

        Returns:
            job client
        """
        if self.host is not None:
            return JobSubmissionClient(f"http://{self.host}:8265")
        return None

    def context(self, **kwargs):
        """Returns context allocated for this cluster."""
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
        """Returns connection string to cluster."""
        if self.host is not None and self.port is not None:
            return f"ray://{self.host}:{self.port}"
        return None

    @classmethod
    def from_dict(cls, data: dict):
        """Created cluster object form dict."""
        return Cluster(
            name=data.get("name"),
            host=data.get("host"),
            port=data.get("port"),
            ip_address=data.get("ip_address"),
        )

    def __eq__(self, other: object):
        if isinstance(other, Cluster):
            return (
                self.name == other.name
                and self.port == other.port
                and self.host == other.host
            )
        return False

    def __repr__(self):
        return f"<Cluster: {self.name}>"


class Provider(JsonSerializable):
    """Provider"""

    def __init__(
        self,
        name: str,
        host: Optional[str] = None,
        token: Optional[str] = None,
        cluster: Optional[Cluster] = None,
        available_clusters: Optional[List[Cluster]] = None,
    ):
        """Provider for serverless computation.

        Example:
            >>> provider = Provider(
            >>>    name="<NAME>",
            >>>    host="<HOST>",
            >>>    token="<TOKEN>",
            >>>    cluster=Cluster(name="<CLUSTER_NAME>", host="<CLUSTER_HOST>"),
            >>> )

        Args:
            name: name of provider
            host: host of provider a.k.a managers host
            token: authentication token for manager
            cluster: selected cluster from provider
            available_clusters: available clusters in provider
        """
        self.name = name
        self.host = host
        self.token = token
        self.cluster = cluster
        if available_clusters is None:
            if cluster is not None:
                available_clusters = [cluster]
            else:
                available_clusters = []
        self.available_clusters = available_clusters

    @classmethod
    def from_dict(cls, dictionary: dict):
        return Provider(**dictionary)

    def job_client(self):
        """Returns job client for configured compute resource of provider.

        Returns:
            job client
        """
        return self.cluster.job_client()

    def context(self, **kwargs):
        """Allocated context for selected cluster for provider."""
        if self.cluster is None:
            raise QuantumServerlessException(
                f"Cluster was not selected for provider {self.name}"
            )
        return self.cluster.context(**kwargs)

    def __eq__(self, other):
        if isinstance(other, Provider):
            return self.name == other.name

        return False

    def __repr__(self):
        return f"<Provider: {self.name}>"
