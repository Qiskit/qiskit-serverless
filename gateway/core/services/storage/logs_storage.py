"""Abstract base class for logs storage."""

from abc import ABC, abstractmethod
from typing import Optional


class LogsStorage(ABC):
    """Abstract interface for job logs storage."""

    @abstractmethod
    def get_public_logs(self) -> Optional[str]:
        """Retrieve public logs for the job."""

    @abstractmethod
    def save_public_logs(self, logs: str) -> None:
        """Persist public logs for the job."""

    @abstractmethod
    def get_private_logs(self) -> Optional[str]:
        """Retrieve private logs for the job (provider jobs only)."""

    @abstractmethod
    def save_private_logs(self, logs: str) -> None:
        """Persist private logs for the job (provider jobs only)."""
