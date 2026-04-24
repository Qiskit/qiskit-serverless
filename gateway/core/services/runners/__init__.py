"""Abstract runner for job execution."""

from core.models import Job, Program
from core.services.runners.abstract_runner import RunnerError, AbstractRunner

from core.services.runners.fleets_runner import FleetsRunner
from core.services.runners.ray_runner import RayRunner


def get_runner(job: Job) -> AbstractRunner:
    """
    Factory: create the appropriate runner for the job.
    The runner is created with the job but does NOT connect automatically.

    Args:
        job: Job instance

    Returns:
        AbstractRunner appropriate for the job's runner type

    Raises:
        RunnerError: If runner type is invalid or not supported
    """
    if job.runner == Program.FLEETS:
        return FleetsRunner(job)
    if job.runner == Program.RAY:
        return RayRunner(job)
    raise RunnerError(f"Unknown runner type: {job.runner}")
