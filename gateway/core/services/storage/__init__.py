"""Factory and exports for services storages."""

from core.models import Job, Program
from core.services.storage.arguments_storage import ArgumentsStorage
from core.services.storage.arguments_storage_ray import RayArgumentsStorage


def get_arguments_storage(job: Job) -> ArgumentsStorage:
    """Factory: return the appropriate ArgumentsStorage for the job's program runner.

    Args:
        job: The Job instance whose program runner determines the implementation.

    Returns:
        An ArgumentsStorage instance appropriate for the runner type.

    Raises:
        ValueError: If the runner type is unknown.
    """
    if job.program.runner == Program.RAY:
        return RayArgumentsStorage(job)
    if job.program.runner == Program.FLEETS:
        # Replace with FleetsArgumentsStorage once implemented
        return RayArgumentsStorage(job)
    raise ValueError(f"Unknown runner type: {job.program.runner}")
