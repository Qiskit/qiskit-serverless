"""Base provider."""

from dataclasses import dataclass
from typing import Optional

from quantum_serverless.exception import QuantumServerlessException

from quantum_serverless import Cluster

from quantum_serverless.utils import JsonSerializable


@dataclass
class Provider(JsonSerializable):
    """Provider"""
    name: str
    host: Optional[str] = None
    token: Optional[str] = None
    cluster: Optional[Cluster] = None

    @classmethod
    def from_dict(cls, dictionary: dict):
        return Provider(**dictionary)

    def context(self, **kwargs):
        """Allocated context for selected cluster for provider."""
        if self.cluster is None:
            raise QuantumServerlessException("Cluster was not selected for provider %s", self.name)
        return self.cluster.context(**kwargs)

    def __eq__(self, other):
        if isinstance(other, Provider):
            return self.name == other.name
        else:
            return False
