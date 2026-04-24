"""Abstract runner for job execution in any engine (Ray, Fleets)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import Job


class RunnerError(Exception):
    """Base exception for runner operations.

    Wraps engine-specific exceptions (e.g., Ray's RuntimeError, CE ApiException)
    to provide a consistent interface for error handling across runners.

    Attributes:
        message: Human-readable error description.
        original_exception: The underlying exception that caused this error, if any.
    """

    def __init__(self, message: str, original_exception: Exception | None = None):
        super().__init__(message)
        self.message = message
        self.original_exception = original_exception

    def __str__(self) -> str:
        if self.original_exception:
            return f"{self.message}: {self.original_exception}"
        return self.message


class AbstractRunner(ABC):
    """Abstract runner for executing jobs on different engines (Ray, Fleets).

    Connection is lazy: established via ``connect()`` or automatically when
    calling methods that require it. Subclasses implement the engine-specific
    lifecycle operations.
    """

    def __init__(self, job: Job) -> None:
        """Initialize the runner with a Job.

        Args:
            job: Job instance to be executed.
        """
        self._job = job
        self._connected = False

    @property
    def job(self) -> Job:
        """Job associated with this runner."""
        return self._job

    @property
    def is_connected(self) -> bool:
        """True if there is an active connection to the engine."""
        return self._connected

    @abstractmethod
    def connect(self) -> None:
        """Establish a connection to the engine.

        Raises:
            RunnerError: If unable to connect.
        """
        raise NotImplementedError

    def _ensure_connected(self) -> None:
        """Connect if not already connected.

        Called internally by methods that require an active connection.
        """
        if not self._connected:
            self.connect()

    @abstractmethod
    def submit(self) -> None:
        """Submit the job to the engine.

        Raises:
            RunnerError: If submission fails.
        """
        raise NotImplementedError

    @abstractmethod
    def is_active(self) -> bool:
        """Return True if the engine host is reachable, even after the job finishes.

        Returns:
            True if the engine host responds.
        """
        raise NotImplementedError

    @abstractmethod
    def status(self) -> str | None:
        """Return the current job status mapped to Job.STATUS.

        Returns:
            Job status string or ``None`` if temporarily unavailable.

        Raises:
            RunnerError: If unable to retrieve status.
        """
        raise NotImplementedError

    @abstractmethod
    def logs(self) -> str | None:
        """Return the user-facing job logs.

        Returns:
            Log content or ``None``.

        Raises:
            RunnerError: If unable to retrieve logs.
        """
        raise NotImplementedError

    def provider_logs(self) -> str | None:
        """Return provider (unfiltered) job logs.

        Engines that support dual-log routing (e.g. Fleets with PDS mounts)
        override this to return the full provider log. The default implementation
        falls back to ``logs()``, which is appropriate for engines that have no
        distinction between user and provider logs (e.g. Ray).

        Returns:
            Provider log content or ``None``.

        Raises:
            RunnerError: If unable to retrieve logs.
        """
        return self.logs()

    @abstractmethod
    def stop(self) -> bool:
        """Stop the running job.

        Returns:
            True if the job was running and was stopped.

        Raises:
            RunnerError: If unable to stop the job.
        """
        raise NotImplementedError

    @abstractmethod
    def free_resources(self) -> bool:
        """Clean up compute resources associated with the job.

        Returns:
            True if resources were cleaned up successfully.
        """
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        """Close the connection to the engine if open."""
        raise NotImplementedError
