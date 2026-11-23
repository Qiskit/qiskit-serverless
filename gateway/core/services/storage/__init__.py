"""Factory and exports for services storages."""

from core.domain.storage_paths import StoragePaths
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


def get_arguments_storage(job: Job, paths: StoragePaths | None) -> ArgumentsStorage:
    """Factory: return the appropriate ArgumentsStorage for the job's runner that ran it.

    Args:
        job: The Job instance whose runner that ran it determines the implementation.
        paths: The paths of a Fleets job: the ones built at creation, before they are saved, or the saved ones
            (:func:`get_storage_paths`). None for a Ray job, which has none.

    Returns:
        An ArgumentsStorage instance appropriate for the runner type.

    Raises:
        ValueError: If the runner type is unknown, or a Fleets job is given no paths.
    """
    if job.runner == Program.RAY:
        return RayArgumentsStorage(job)
    if job.runner == Program.FLEETS:
        if paths is None:
            raise ValueError(f"Fleets job '{job.id}' needs its storage paths to read or write its arguments")
        return FleetsArgumentsStorage(job, paths)
    raise ValueError(f"Unknown runner type: {job.runner}")


def get_logs_storage(job: Job) -> LogsStorage:
    """Factory: return the appropriate LogsStorage for the job's runner that ran it.

    Args:
        job: The Job instance whose runner that ran it determines the implementation.

    Returns:
        A LogsStorage instance appropriate for the runner type.

    Raises:
        ValueError: If the runner type is unknown.
    """
    if job.runner == Program.RAY:
        return RayLogsStorage(job)
    if job.runner == Program.FLEETS:
        return FleetsLogsStorage(job)
    raise ValueError(f"Unknown runner type: {job.runner}")


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
    """Factory: return the appropriate ResultStorage for the job's runner that ran it.

    Args:
        job: The Job instance whose runner that ran it determines the implementation.

    Returns:
        A ResultStorage instance appropriate for the runner type.

    Raises:
        ValueError: If the runner type is unknown.
    """
    if job.runner == Program.RAY:
        return RayResultStorage(job)
    if job.runner == Program.FLEETS:
        return FleetsResultStorage(job)
    raise ValueError(f"Unknown runner type: {job.runner}")
