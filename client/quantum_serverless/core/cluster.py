"""Cluster classes."""
from dataclasses import dataclass
from typing import Dict, List, Optional

from quantum_serverless.exception import QuantumServerlessException


@dataclass
class Node:
    """Cluster node class."""

    node_id: str
    resource: Dict[str, float]


@dataclass
class Cluster:
    """Cluster class.

    Args:
        name: name of cluster
        host: host address of cluster
        port: port of cluster
        ip_address: ip address of cluster
        nodes: list of nodes for cluster
        resources: list of resrouces
    """

    name: str
    host: Optional[str] = None
    port: Optional[int] = None
    ip_address: Optional[str] = None
    nodes: Optional[List[Node]] = None
    resources: Optional[Dict[str, float]] = None
    is_local: bool = False

    def connection_string_interactive_mode(self) -> Optional[str]:
        """Returns connection string to cluster."""
        if self.host is not None and self.port is not None:
            return f"ray://{self.host}:{self.port}"
        return None

    def connection_string_job_server(self):
        """Return connection string for job server."""
        if self.host is None:
            raise QuantumServerlessException(
                f"Your cluster must have host. "
                f"You are trying to connect to {self.name} "
                f"which is not a viable cluster for job execution."
            )
        return f"http://{self.host}:8265"

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
