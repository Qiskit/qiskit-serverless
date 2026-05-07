"""Factory and exports for services storages."""

from core.models import Program
from core.services.storage.arguments_storage import ArgumentsStorage
from core.services.storage.arguments_storage_ray import RayArgumentsStorage
from core.services.storage.arguments_storage_fleets import FleetsArgumentsStorage


def get_arguments_storage(username: str, function: Program) -> ArgumentsStorage:
    """Factory: return the appropriate ArgumentsStorage for the program's runner.

    Args:
        username: The job author's username.
        function: The Program instance whose runner determines the implementation.

    Returns:
        An ArgumentsStorage instance appropriate for the runner type.

    Raises:
        ValueError: If the runner type is unknown.
    """
    if function.runner == Program.RAY:
        return RayArgumentsStorage(username, function)
    if function.runner == Program.FLEETS:
        return FleetsArgumentsStorage(username, function)
    raise ValueError(f"Unknown runner type: {function.runner}")
