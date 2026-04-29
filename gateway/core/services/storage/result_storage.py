"""
This module handle the access to the result store
"""

import logging
from typing import Optional

from core.models import Job
from core.services.storage import get_cos
from core.services.storage.enums.working_dir import WorkingDir

logger = logging.getLogger("core.ResultStorage")


class ResultStorage:
    """Handles the storage and retrieval of user job results via COS."""

    RESULT_FILE_EXTENSION = ".json"
    PATH = "results"

    def __init__(self, job: Job):
        self._username = job.author.username
        self._cos = get_cos(job)

    def _key(self, job_id: str) -> str:
        return f"{self._username}/{self.PATH}/{job_id}{self.RESULT_FILE_EXTENSION}"

    def get(self, job_id: str) -> Optional[str]:
        """Retrieve a result for the given job ID from COS."""
        content = self._cos.get_object(self._key(job_id), WorkingDir.USER_STORAGE)
        if content is None:
            logger.info("[get] job_id=%s Result not found in COS", job_id)
        return content

    def save(self, job_id: str, result: str) -> None:
        """Save the result for the given job ID to COS."""
        self._cos.put_object(self._key(job_id), result, WorkingDir.USER_STORAGE)
        logger.info("[save] job_id=%s Result saved to COS", job_id)
