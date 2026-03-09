"""Runner clients for job execution."""

from core.models import Job
from core.services.runners.runner_client import RunnerError, RunnerClient

from core.services.runners.ray_client import RayClient


def get_runner_client(job: Job) -> RunnerClient:
    """
    Factory: create the appropriate client for the job.
    The client is created with the job but does NOT connect automatically.

    Args:
        job: Job instance

    Returns:
        RunnerClient appropriate for the job's runner type
    """

    # Future extension when job.runner is available:
    # from core.services.runners.fleets_client import FleetsClient
    # if job.runner == Runner.FLEETS:
    #     return FleetsClient(job)
    return RayClient(job)
