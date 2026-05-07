"""Fleets implementation of arguments storage."""

from typing import Optional

from core.models import Program
from core.services.storage.arguments_storage import ArgumentsStorage


class FleetsArgumentsStorage(ArgumentsStorage):
    """Handles the storage and retrieval of user arguments for Fleets jobs."""

    def __init__(self, username: str, function: Program) -> None:
        pass

    def get(self, job_id: str) -> Optional[str]:
        raise NotImplementedError

    def save(self, job_id: str, arguments: str) -> None:
        raise NotImplementedError
