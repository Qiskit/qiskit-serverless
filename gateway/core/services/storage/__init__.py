"""Factory and exports for services storages."""

from core.models import Job, Program
from core.services.storage.arguments_storage import ArgumentsStorage
from core.services.storage.arguments_storage_fleets import FleetsArgumentsStorage
from core.services.storage.arguments_storage_ray import RayArgumentsStorage
from core.services.storage.logs_storage import LogsStorage
from core.services.storage.logs_storage_ray import RayLogsStorage


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
        return FleetsArgumentsStorage(job)
    raise ValueError(f"Unknown runner type: {job.program.runner}")


def get_logs_storage(job: Job) -> LogsStorage:
    """Factory: return the appropriate LogsStorage for the job's program runner.

    Args:
        job: The Job instance whose program runner determines the implementation.

    Returns:
        A LogsStorage instance appropriate for the runner type.

    Raises:
        ValueError: If the runner type is unknown.
    """
    if job.program.runner == Program.RAY:
        return RayLogsStorage(job)
    if job.program.runner == Program.FLEETS:
        # We will use RayLogs until we have the implementation in fleets
        return RayLogsStorage(job)
    raise ValueError(f"Unknown runner type: {job.program.runner}")
