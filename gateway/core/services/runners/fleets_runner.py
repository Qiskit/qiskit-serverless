"""Fleets runner placeholder for future implementation."""

from typing import Optional

from core.services.runners.abstract_runner import AbstractRunner, SubmitResult


class FleetsRunner(AbstractRunner):
    """Runner for executing jobs on Fleets."""

    def connect(self) -> None:
        """Lazy call to connect to CodeEngine (create the SDK)"""

    def disconnect(self) -> None:
        """Disconnect from CodeEngine?? (remove the SDK)"""

    def submit(self) -> any:
        """Submit the job to Fleets."""
        raise NotImplementedError("FleetsRunner not yet implemented")

    def status(self) -> Optional[str]:
        """Get job status."""
        raise NotImplementedError("FleetsRunner not yet implemented")

    def logs(self) -> Optional[str]:
        """Get job logs."""
        raise NotImplementedError("FleetsRunner not yet implemented")

    def stop(self) -> bool:
        """Stop the job."""
        raise NotImplementedError("FleetsRunner not yet implemented")

    def free_resources(self) -> bool:
        """Clean up resources."""
        raise NotImplementedError("FleetsRunner not yet implemented")
