"""Quantum serverless."""
import json
import logging
import os
from abc import ABC
from typing import Optional, Union, List, Dict, Any

import requests
from ray._private.worker import BaseContext

from quantum_serverless.core import Cluster
from quantum_serverless.core.provider.provider import Provider
from quantum_serverless.exception import QuantumServerlessException
from quantum_serverless.serializers import register_all_serializers

Context = Union[BaseContext]


class BaseQuantumServerless(ABC):
    """BaseQuantumServerless class."""

    @classmethod
    def load_configuration(cls, path: str) -> "BaseQuantumServerless":
        """Creates QuantumServerless object from configuration."""
        raise NotImplementedError

    def provider(self, provider: Union[str, Provider], cluster: Optional[Union[str, Cluster]] = None) -> Context:
        """Allocate context with selected provider and cluster.

        Example:
            >>> quantum_serverless = QuantumServerless()
            >>> with quantum_serverless.provider("ibm"):
            >>>     ...

        Args:
            provider:
            cluster:

        Returns:

        """
        raise NotImplementedError

    def cluster(self) -> Context:
        """Allocate context with selected cluster.

        Example:
            >>> quantum_serverless = QuantumServerless()
            >>> with quantum_serverless.cluster("<MY_CLUSTER>"):
            >>>     ...

        Returns:
            Execution context.
        """
        raise NotImplementedError

    def add_provider(self, provider: Provider) -> "BaseQuantumServerless":
        """Adds provider."""
        raise NotImplementedError

    def set_provider(self, provider: Union[str, int, Provider]) -> "BaseQuantumServerless":
        """Set specific provider."""
        raise NotImplementedError

    def providers(self) -> List[Provider]:
        """Returns list of available providers."""
        raise NotImplementedError

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
                str for name of cluster in list
                or Cluster object.

        Returns:
            self reference
        """
        raise NotImplementedError

    def context(self, **kwargs) -> Context:
        """Creates execution context for serverless workloads."""
        raise NotImplementedError


class QuantumServerless(BaseQuantumServerless):
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
        pass

    def __init__(self, config: Dict[str, Any]):
        """Quantum serverless management class.

        Example:
            >>> configuration = {"providers": [{"name": "<NAME>", "host": "<HOST>", "token": "<TOKEN>"}]}
            >>> quantum_serverless = QuantumServerless(configuration)

        Args:
            config: configuration

        Example:
            >>> from quantum_serverless import QuantumServerless
            >>> serverless = QuantumServerless()

        Raises:
            QuantumServerlessException
        """
        self.providers: List[Provider] = load_config(config)
        self._selected_provider: Optional[Provider] = None

        self.manager_address = os.environ.get("QS_CLUSTER_MANAGER_ADDRESS", None)
        self._selected_cluster: Optional[Cluster] = None
        self._clusters = self._get_clusters()
        self.set_cluster(0)

    def provider(self, provider: Union[str, Provider], cluster: Optional[Union[str, Cluster]] = None) -> Context:
        pass

    def cluster(self) -> Context:
        pass

    def add_provider(self, provider: Provider) -> "BaseQuantumServerless":
        pass

    def set_provider(self, provider: Union[str, int, Provider]) -> "BaseQuantumServerless":
        pass

    def providers(self) -> List[Provider]:
        pass

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

        return self._selected_cluster.context(**kwargs)


def load_config(config: Dict[str, Any]) -> List[Provider]:
    """Loads providers from configuration."""
    local_provider = Provider(
        name="local",
        cluster=Cluster(name="local")
    )
    providers = [local_provider]

    for provider_config in config.get("providers", []):
        providers.append(Provider(**provider_config))

    return providers


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
