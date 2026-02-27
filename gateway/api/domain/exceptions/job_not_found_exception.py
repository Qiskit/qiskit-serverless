"""Job not found exception."""

from typing import Optional
from api.domain.exceptions.not_found_exception import NotFoundError


class JobNotFoundException(NotFoundError):
    """Exception raised when a job is not found."""

    def __init__(self, job_id: str, reason: Optional[str] = None):
        self.job_id = job_id
        self.reason = reason
        message = f"Job [{job_id}] not found"
        if reason:
            message = f"{message}: {reason}"
        super().__init__(message)
