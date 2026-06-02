"""Fleets implementation of result storage."""

from __future__ import annotations

from typing import Optional

from core.models import Job
from core.services.storage.result_storage import ResultStorage


class FleetsResultStorage(ResultStorage):
    """Handles the storage and retrieval of user job results for Fleets jobs."""

    def __init__(self, job: Job) -> None:
        self._job_id = str(job.id)

    def get(self) -> Optional[str]:
        """Retrieve the result for this job."""
        raise NotImplementedError

    def save(self, result: str) -> None:
        """Persist the result for this job."""
        raise NotImplementedError
