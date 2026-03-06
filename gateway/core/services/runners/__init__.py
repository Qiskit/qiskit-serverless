"""Runner clients for job execution backends."""

from core.services.runners.runner import Runner
from core.services.runners.runner_client import RunnerError


def get_runner_client(job):
    """
    Factory: create the appropriate client for the job.
    The client is created with the job but does NOT connect automatically.

    Args:
        job: Job instance

    Returns:
        RunnerClient appropriate for the job's runner type
    """
    # pylint: disable=import-outside-toplevel
    # Imported here to avoid circular imports.
    from core.services.runners.ray_client import RayClient

    # Future extension when job.runner is available:
    # from core.services.runners.fleets_client import FleetsClient
    # if job.runner == Runner.FLEETS:
    #     return FleetsClient(job)
    return RayClient(job)


__all__ = [
    "Runner",
    "RunnerError",
    "get_runner_client",
]
