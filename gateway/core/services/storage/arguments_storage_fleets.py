"""Fleets implementation of arguments storage."""

from typing import Optional

from core.models import Job
from core.services.storage.arguments_storage import ArgumentsStorage


class FleetsArgumentsStorage(ArgumentsStorage):
    """Handles the storage and retrieval of user arguments for Fleets jobs."""

    def __init__(self, job: Job) -> None:
        self._job_id = str(job.id)

    def get(self) -> Optional[str]:
        raise NotImplementedError

    def save(self, arguments: str) -> None:
        raise NotImplementedError
