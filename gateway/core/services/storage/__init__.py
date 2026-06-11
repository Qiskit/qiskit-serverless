"""Factory and exports for services storages."""

from core.models import Job, Program
from core.services.storage.arguments_storage import ArgumentsStorage
from core.services.storage.arguments_storage_fleets import FleetsArgumentsStorage
from core.services.storage.arguments_storage_ray import RayArgumentsStorage
from core.services.storage.file_storage import FileStorage
from core.services.storage.file_storage_fleets import FileStorageFleets
from core.services.storage.file_storage_ray import FileStorageRay
from core.services.storage.logs_storage import LogsStorage
from core.services.storage.logs_storage_fleets import FleetsLogsStorage
from core.services.storage.logs_storage_ray import RayLogsStorage
from core.services.storage.result_storage import ResultStorage
from core.services.storage.result_storage_fleets import FleetsResultStorage
from core.services.storage.result_storage_ray import RayResultStorage


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
        return FleetsLogsStorage(job)
    raise ValueError(f"Unknown runner type: {job.program.runner}")


def get_file_storage(
    username: str,
    function: Program,
) -> FileStorage:
    """Factory: return the appropriate FileStorage for the job's program runner.

    Args:
        job: The Job instance whose program runner determines the implementation.

    Returns:
        A FileStorage instance appropriate for the runner type.

    Raises:
        ValueError: If the runner type is unknown.
    """
    if function.runner == Program.RAY:
        return FileStorageRay(username, function)
    if function.runner == Program.FLEETS:
        return FileStorageFleets(username, function)
    raise ValueError(f"Unknown runner type: {function.runner}")


def get_result_storage(job: Job) -> ResultStorage:
    """Factory: return the appropriate ResultStorage for the job's program runner.

    Args:
        job: The Job instance whose program runner determines the implementation.

    Returns:
        A ResultStorage instance appropriate for the runner type.

    Raises:
        ValueError: If the runner type is unknown.
    """
    if job.program.runner == Program.RAY:
        return RayResultStorage(job)
    if job.program.runner == Program.FLEETS:
        return FleetsResultStorage(job)
    raise ValueError(f"Unknown runner type: {job.program.runner}")
