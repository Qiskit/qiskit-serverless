"""Runner clients for job execution."""

from core.models import Job
from core.services.runners.abstract_runner import RunnerError, AbstractRunner

from core.services.runners.ray_runner import RayRunner


def get_runner(job: Job) -> AbstractRunner:
    """
    Factory: create the appropriate runner for the job.
    The runner is created with the job but does NOT connect automatically.

    Args:
        job: Job instance

    Returns:
        AbstractRunner appropriate for the job's runner type
    """

    # Future extension when job.runner is available:
    # from core.services.runners.fleets_client import FleetsRunner
    # if job.runner == Runner.FLEETS:
    #     return FleetsRunner(job)
    return RayRunner(job)
