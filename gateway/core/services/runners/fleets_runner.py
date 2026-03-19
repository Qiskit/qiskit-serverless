"""Fleets runner placeholder for future implementation."""

from typing import Optional

from core.models import ComputeResource
from core.services.runners.abstract_runner import AbstractRunner


class FleetsRunner(AbstractRunner):
    """Runner for executing jobs on Fleets."""

    def connect(self) -> None:
        """Lazy call to connect to CodeEngine (create the SDK)"""

    def disconnect(self) -> None:
        """Disconnect from CodeEngine?? (remove the SDK)"""

    def submit(self) -> tuple[ComputeResource, str]:
        """
        Submit the job to Fleets.

        Returns:
            Tuple of (ComputeResource, job_id)
            - ComputeResource: not saved to DB, caller must save and assign to job
            - job_id: CodeEngine job identifier
        """
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
