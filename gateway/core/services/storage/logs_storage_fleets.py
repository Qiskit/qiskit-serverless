"""Fleets implementation of logs storage."""

from __future__ import annotations

from typing import Optional

from core.models import Job
from core.services.storage.logs_storage import LogsStorage


class FleetsLogsStorage(LogsStorage):
    """Handles the storage and retrieval of logs for Fleets jobs."""

    def __init__(self, job: Job) -> None:
        self._job_id = str(job.id)

    def get_public_logs(self) -> Optional[str]:
        raise NotImplementedError

    def save_public_logs(self, logs: str) -> None:
        raise NotImplementedError

    def get_private_logs(self) -> Optional[str]:
        raise NotImplementedError

    def save_private_logs(self, logs: str) -> None:
        raise NotImplementedError
