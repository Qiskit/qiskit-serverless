"""Abstract cos module."""

from abc import ABC, abstractmethod
from typing import Optional

from core.services.storage.enums.working_dir import WorkingDir


class COSError(Exception):
    """Base exception for COS operations.

    Attributes:
        message: Human-readable error description
        original_exception: The underlying exception that caused this error (if any)
    """

    def __init__(self, message: str, original_exception: Exception = None):
        super().__init__(message)
        self.message = message
        self.original_exception = original_exception

    def __str__(self):
        if self.original_exception:
            return f"{self.message}: {self.original_exception}"
        return self.message


class AbstractCOSClient(ABC):
    """Abstract COS client for object storage operations."""

    @abstractmethod
    def get_object(self, key: str, working_dir: WorkingDir = WorkingDir.USER_STORAGE) -> Optional[str]:
        """Get object content from COS as a UTF-8 string."""
        raise NotImplementedError

    @abstractmethod
    def put_object(self, key: str, content: str, working_dir: WorkingDir = WorkingDir.USER_STORAGE) -> None:
        """Write a UTF-8 string to COS."""
        raise NotImplementedError

    @abstractmethod
    def get_object_bytes(self, key: str, working_dir: WorkingDir = WorkingDir.USER_STORAGE) -> Optional[bytes]:
        """Get object content from COS as raw bytes."""
        raise NotImplementedError

    @abstractmethod
    def get_object_for_stream(self, key: str, working_dir: WorkingDir = WorkingDir.USER_STORAGE) -> Optional[bytes]:
        """Get object content from COS as raw bytes."""
        raise NotImplementedError

    @abstractmethod
    def put_object_bytes(self, key: str, content: bytes, working_dir: WorkingDir = WorkingDir.USER_STORAGE) -> None:
        """Write raw bytes to COS."""
        raise NotImplementedError

    @abstractmethod
    def delete_object(self, key: str, working_dir: WorkingDir = WorkingDir.USER_STORAGE) -> bool:
        """Delete an object from COS. Returns True on success."""
        raise NotImplementedError

    @abstractmethod
    def list_objects(self, prefix: str, working_dir: WorkingDir = WorkingDir.USER_STORAGE) -> list[str]:
        """List object keys under the given prefix."""
        raise NotImplementedError
