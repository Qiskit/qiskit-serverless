from core.models import Job, Program
from core.services.storage.abstract_cos_client import COSError, AbstractCOSClient
from core.services.storage.fleets_cos_client import FleetsCOSClient
from core.services.storage.ray_cos_client import RayCOSClient


def get_cos(job: Job) -> AbstractCOSClient:
    """
    Factory: create the appropriate COS client for the job.

    Args:
        job: Job instance

    Returns:
        AbstractCOSClient appropriate for the job's runner type

    Raises:
        COSError: If runner type is invalid or not supported
    """
    if job.runner == Program.FLEETS:
        return FleetsCOSClient(job)
    if job.runner == Program.RAY:
        return RayCOSClient(job)
    raise COSError(f"Unknown runner type: {job.runner}")


def get_cos_for_program(program: Program) -> AbstractCOSClient:
    """
    Factory: create the appropriate COS client for a program (no job context).

    Used by file management operations where no Job is available.

    Args:
        program: Program instance

    Returns:
        AbstractCOSClient appropriate for the program's runner type

    Raises:
        COSError: If runner type is invalid or not supported
    """
    if program.runner == Program.FLEETS:
        return FleetsCOSClient()
    if program.runner == Program.RAY:
        return RayCOSClient()
    raise COSError(f"Unknown runner type: {program.runner}")
