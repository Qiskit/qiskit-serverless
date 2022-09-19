"""Quantum serverless."""
import json
import logging
import os
from abc import ABC
from typing import Optional, Union, List

import ray
import requests
from ray._private.worker import BaseContext
from ray.job_submission import JobSubmissionClient

from quantum_serverless.core.cluster import Cluster
from quantum_serverless.exception import QuantumServerlessException
from quantum_serverless.serializers import register_all_serializers

Context = Union[BaseContext]


class BaseQuantumServerless(ABC):
    """BaseQuantumServerless class."""

    def clusters(self) -> List[Cluster]:
        """Returns list of available clusters."""
        raise NotImplementedError

    def add_cluster(self, cluster: Cluster) -> "BaseQuantumServerless":
        """Adds cluster to list of available clusters

        Args:
            cluster: cluster to add

        Returns:
            self reference
        """
        raise NotImplementedError

    def set_cluster(self, cluster: Union[int, str, Cluster]) -> "BaseQuantumServerless":
        """Sets cluster to use for context.

        Args:
            cluster: Can be int for index in list,
                str for name of clsuter in list
                or Cluster object.

        Returns:
            self reference
        """
        raise NotImplementedError

    def context(self, **kwargs) -> Context:
        """Creates execution context for serverless workloads."""
        raise NotImplementedError

    def get_job_client(self) -> JobSubmissionClient:
        """Returns job client."""
        raise NotImplementedError


class QuantumServerless(BaseQuantumServerless):
    """QuantumServerless class."""

    def __init__(
        self, token: Optional[str] = None, manager_address: Optional[str] = None
    ):
        """Quantum serverless management class.

        Args:
            token: authentication token
            manager_address: address for cluster manager

        Example:
            >>> from quantum_serverless import QuantumServerless
            >>> serverless = QuantumServerless()
            >>> with serverless.context():
            ...     pass # workload

        Raises:
            QuantumServerlessException
        """
        if token is None:
            token = os.environ.get("QS_TOKEN", None)
        self.token = token

        if manager_address is None:
            manager_address = os.environ.get("QS_CLUSTER_MANAGER_ADDRESS", None)
        self.manager_address = manager_address

        # set up clusters
        self._selected_cluster: Optional[Cluster] = None
        self._clusters = self._get_clusters()
        self.set_cluster(0)

    def _get_clusters(self) -> List[Cluster]:
        """Get list of available clusters

        Returns:
            list of available clusters
        """
        clusters = [
            Cluster("local", resources={"QPU": 1}),
        ]  # local machine
        if self.manager_address is not None:
            clusters += get_clusters(self.manager_address, token=self.token)
        return clusters

    def clusters(self) -> List[Cluster]:
        return self._clusters

    def add_cluster(self, cluster: Cluster) -> "BaseQuantumServerless":
        if cluster in self._clusters:
            logging.warning(
                "%s cluster already in list of available clusters. Skipping addition...",
                cluster.name,
            )
        else:
            self._clusters.append(cluster)
        return self

    def set_cluster(self, cluster: Union[int, str, Cluster]) -> "QuantumServerless":
        clusters = self._clusters
        if isinstance(cluster, int):
            if len(clusters) <= cluster:
                raise QuantumServerlessException(
                    f"Selected index is out of bounds. "
                    f"You picked {cluster} index whereas only {len(clusters)}"
                    f"available"
                )
            self._selected_cluster = clusters[cluster]

        elif isinstance(cluster, str):
            cluster_names = [c.name for c in clusters]
            if cluster not in cluster_names:
                raise QuantumServerlessException(
                    f"{cluster} name is not in a list "
                    f"of available cluster names: {cluster_names}."
                )
            self._selected_cluster = clusters[cluster_names.index(cluster)]

        elif isinstance(cluster, Cluster):
            if cluster not in clusters:
                self.add_cluster(cluster)
            self._selected_cluster = cluster

        return self

    def context(self, **kwargs) -> Context:
        """Returns Ray context for tasks/actors execution."""
        if self._selected_cluster is None:
            self._selected_cluster = self._clusters[0]

        # register custom serializers
        register_all_serializers()

        init_args = {
            **kwargs,
            **{
                "address": kwargs.get(
                    "address",
                    self._selected_cluster.connection_string_interactive_mode(),
                ),
                "ignore_reinit_error": kwargs.get("ignore_reinit_error", True),
                "logging_level": kwargs.get("logging_level", "warning"),
                "local_mode": kwargs.get("local_mode", self._selected_cluster.is_local),
                "resources": kwargs.get("resources", self._selected_cluster.resources),
            },
        }

        return ray.init(**init_args)

    def get_job_client(self) -> JobSubmissionClient:
        if self._selected_cluster is None:
            self._selected_cluster = self._clusters[0]

        return JobSubmissionClient(
            self._selected_cluster.connection_string_job_server()
        )

    def __repr__(self):
        return f"QuantumServerless:\n | selected cluster: {self._selected_cluster}"


def get_clusters(manager_address: str, token: Optional[str] = None) -> List[Cluster]:
    """Makes http request to middleware to get available clusters."""
    clusters = []

    headers = {"Authorization": f"Bearer {token}"} if token else None
    url = f"{manager_address}/quantum-serverless-middleware/cluster/"

    response = requests.get(url, headers=headers, timeout=10)
    if response.ok:
        cluster_names_response = json.loads(response.text)
        for cluster_name in cluster_names_response:
            name = cluster_name.get("name")
            cluster_details_response = requests.get(
                f"{url}{name}", headers=headers, timeout=10
            )
            if cluster_details_response.ok and name:
                clusters.append(
                    Cluster.from_dict(json.loads(cluster_details_response.text))
                )
    else:
        logging.warning(
            "Something went wrong when trying to connect to cluster manager: [%d] %s",
            response.status_code,
            response.text,
        )

    return clusters
