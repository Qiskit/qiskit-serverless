"""Abstract base class for result storage."""

from abc import ABC, abstractmethod
from typing import Optional


class ResultStorage(ABC):
    """Abstract interface for job result storage."""

    @abstractmethod
    def get(self) -> Optional[str]:
        """Retrieve the result for the job."""

    @abstractmethod
    def save(self, result: str) -> None:
        """Persist the result for the job."""

    @abstractmethod
    def get_url(self) -> Optional[str]:
        """Return a presigned URL for the result, or None if not available."""
