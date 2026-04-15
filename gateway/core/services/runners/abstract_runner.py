"""Abstract runner for job execution in any engine (Ray, Fleets)."""

from abc import ABC, abstractmethod
from typing import Optional

from core.models import Job, ComputeResource


class RunnerError(Exception):
    """Base exception for runner operations.

    This exception is raised when a runner operation fails (status, logs, stop, submit).
    It wraps the underlying engine-specific exceptions (e.g., Ray's RuntimeError)
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


class AbstractRunner(ABC):
    """Abstract runner for executing jobs on different engines."""

    def __init__(self, job: Job):
        """
        Initialize the runner with a Job.

        Connection to Ray/Fleets is lazy: established via connect() or automatically when calling methods that
        require it. This approach was taken because creation of the Ray runner always makes a first connection
        to the server just to check if the version matches. That means that just by creating the runner class,
        it can throw a connection error if Ray node is down or an IO problem, which is quite annoying.
        By making it lazy, we ensure that the runner creation never fails and that only actual operations
        (such as logs(), status(), etc.) are the ones that can fail when connecting.

        Note: job.compute_resource may be None when creating the runner for job submission.
        The submit() method will create and assign it to the job, but the caller is
        responsible for saving the job to DB afterward.

        Args:
            job: Job instance to be executed
        """
        self._job = job
        self._connected = False

    @property
    def job(self) -> Job:
        """Job associated with this runner."""
        return self._job

    @property
    def is_connected(self) -> bool:
        """True if there's an active connection to the engine."""
        return self._connected

    @abstractmethod
    def connect(self) -> None:
        """
        Establish explicit connection to the Ray or Fleet, if it's really needed.

        Raises:
            RunnerError: If unable to connect to the engine
        """
        raise NotImplementedError

    def _ensure_connected(self) -> None:
        """Connect if not connected. Called internally by methods that require connection."""
        if not self._connected:
            self.connect()

    # --- Methods that do NOT require connection ---

    @abstractmethod
    def submit(self):
        """
        Submit the job to the runner.

        Creates the compute resource and submits the job.
        On failure, cleans up any created resources (e.g., K8s cluster).

        Raises:
            RunnerError: If submission fails (resources are cleaned up before raising)
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
        """Close connection to engine if open."""
        raise NotImplementedError
