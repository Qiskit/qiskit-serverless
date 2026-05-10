"""Abstract base class for arguments storage."""

from abc import ABC, abstractmethod
from typing import Optional


class ArgumentsStorage(ABC):
    """Abstract interface for job arguments storage."""

    @abstractmethod
    def get(self) -> Optional[str]:
        """Retrieve arguments for the job."""

    @abstractmethod
    def save(self, arguments: str) -> None:
        """Persist arguments for the job."""
