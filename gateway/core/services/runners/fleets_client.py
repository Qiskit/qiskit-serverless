"""Fleets client placeholder for future implementation."""

from typing import Optional

from core.models import Job, ComputeResource
from core.services.runners.runner_client import RunnerClient


class FleetsClient(RunnerClient):
    """Client for executing jobs on Fleets (placeholder for future implementation)."""

    def __init__(self, job: Job):
        """
        Initialize Fleets client with a job.

        Args:
            job: Job instance to be executed
        """
        super().__init__(job)

    def connect(self) -> None:
        """Connect to Fleets backend."""
        raise NotImplementedError("FleetsClient not yet implemented")

    def disconnect(self) -> None:
        """Disconnect from Fleets backend."""
        raise NotImplementedError("FleetsClient not yet implemented")

    def create_compute_resource(self) -> ComputeResource:
        """Create compute resource for the job."""
        raise NotImplementedError("FleetsClient not yet implemented")

    def submit(self) -> Job:
        """Submit the job to Fleets."""
        raise NotImplementedError("FleetsClient not yet implemented")

    def status(self) -> Optional[str]:
        """Get job status."""
        raise NotImplementedError("FleetsClient not yet implemented")

    def logs(self) -> Optional[str]:
        """Get job logs."""
        raise NotImplementedError("FleetsClient not yet implemented")

    def stop(self) -> bool:
        """Stop the job."""
        raise NotImplementedError("FleetsClient not yet implemented")

    def free_resources(self) -> bool:
        """Clean up resources."""
        raise NotImplementedError("FleetsClient not yet implemented")
