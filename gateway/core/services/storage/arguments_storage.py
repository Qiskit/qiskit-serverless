"""Abstract base class for arguments storage."""

from abc import ABC, abstractmethod
from typing import Optional


class ArgumentsStorage(ABC):
    """Abstract interface for job arguments storage."""

    @abstractmethod
    def get(self, job_id: str) -> Optional[str]:
        """Retrieve arguments for the given job ID."""

    @abstractmethod
    def save(self, job_id: str, arguments: str) -> None:
        """Persist arguments for the given job ID."""
