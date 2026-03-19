"""Fleets runner placeholder for future implementation."""

from typing import Optional

from core.models import ComputeResource, Job
from core.services.runners.abstract_runner import AbstractRunner


class FleetsRunner(AbstractRunner):
    """Runner for executing jobs on Fleets."""

    def __init__(self, job: Job):
        """
        Initialize Fleets runner with a job.

        Args:
            job: Job instance to be executed
        """
        super().__init__(job)

    def connect(self) -> None:
        """Lazy call to connect to CodeEngine (create the SDK)"""
        pass

    def disconnect(self) -> None:
        """Disconnect from CodeEngine?? (remove the SDK)"""
        pass

    def submit(self) -> tuple[ComputeResource, str]:
        """
        Submit the job to Fleets.

        Returns:
            Tuple of (ComputeResource, fleets_id)
            - ComputeResource: not saved to DB, caller must save and assign to job
            - fleets_id: CodeEngine job identifier
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
