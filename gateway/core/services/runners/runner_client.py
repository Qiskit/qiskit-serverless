"""Abstract runner client for job execution backends."""

from abc import ABC, abstractmethod
from typing import Any, Optional

from core.models import Job, ComputeResource


class RunnerError(Exception):
    """Base exception for runner operations.

    This exception is raised when a runner operation fails (status, logs, stop, submit).
    It wraps the underlying backend-specific exceptions (e.g., Ray's RuntimeError)
    to provide a consistent interface for error handling.

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


class RunnerClient(ABC):
    """Abstract client for executing jobs on different backends."""

    def __init__(self, job: Job):
        """
        Initialize the client with a Job.

        Connection to Ray/Fleets is lazy: established via connect() or automatically when calling methods that
        require it. This approach was taken because creation of the Ray client always makes a first connection
        to the server just to check if the version matches. That means that just by creating the client class,
        it can throw a connection error if Ray node is down or an IO problem, which is quite annoying.
        By making it lazy, we ensure that the client creation never fails and that only actual operations
        (such as logs(), status(), etc.) are the ones that can fail when connecting.

        Args:
            job: Job instance to be executed
        """
        self._job = job
        self._connected = False

    @property
    def job(self) -> Job:
        """Job associated with this client."""
        return self._job

    @property
    def is_connected(self) -> bool:
        """True if there's an active connection to the backend."""
        return self._connected

    @abstractmethod
    def connect(self) -> None:
        """
        Establish explicit connection to the Ray or Fleet, if it's really needed.

        Raises:
            RunnerError: If unable to connect to the backend
        """
        raise NotImplementedError

    def _ensure_connected(self) -> None:
        """Connect if not connected. Called internally by methods that require connection."""
        if not self._connected:
            self.connect()

    # --- Methods that do NOT require connection ---

    @abstractmethod
    def submit(self) -> Any:
        """
        Submit the job to the runner.
        Does NOT require connection because the cluster may not exist.

        Returns:
            Backend-specific job identifier (e.g., ray_job_id for Ray)

        Raises:
            RunnerError: If job submission fails
        """
        raise NotImplementedError

    @abstractmethod
    def create_compute_resource(self) -> ComputeResource:
        """
        Create compute resource for the job.
        Does NOT require connection (it's creating the resource).

        Returns:
            ComputeResource instance

        Raises:
            RunnerError: If unable to create compute resource
        """
        raise NotImplementedError

    # --- Methods that DO require connection (lazy connect) ---

    @abstractmethod
    def status(self) -> Optional[str]:
        """
        Get job status (mapped to Job.STATUS).
        Automatically connects if not connected.

        Returns:
            Job status string or None

        Raises:
            RunnerError: If unable to get job status
        """
        raise NotImplementedError

    @abstractmethod
    def logs(self) -> Optional[str]:
        """
        Get job logs.
        Automatically connects if not connected.

        Returns:
            Job logs or None

        Raises:
            RunnerError: If unable to get job logs
        """
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> bool:
        """
        Stop the job.
        Automatically connects if not connected.

        Returns:
            True if job was running and stopped

        Raises:
            RunnerError: If unable to stop the job
        """
        raise NotImplementedError

    # --- Resource cleanup ---

    @abstractmethod
    def free_resources(self) -> bool:
        """
        Clean up/delete the compute resource associated with the job.

        Returns:
            True if cleaned up correctly
        """
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        """Close connection to backend if open."""
        raise NotImplementedError
