"""
This module handle the access to the arguments store
"""

import logging
from typing import Optional

from core.models import Job
from core.services.storage import get_cos
from core.services.storage.enums.working_dir import WorkingDir
from core.services.storage.path_builder import PathBuilder

logger = logging.getLogger("core.ArgumentsStorage")


class ArgumentsStorage:
    """Handles the storage and retrieval of user arguments via COS."""

    ARGUMENTS_FILE_EXTENSION = ".json"
    PATH = "arguments"

    def __init__(self, job: Job):
        username = job.author.username
        function_title = job.program.title
        provider_name = job.program.provider.name if job.program.provider else None
        self._cos = get_cos(job)

        # Arguments are always stored in the user folder
        self._sub_path = PathBuilder.sub_path(
            working_dir=WorkingDir.USER_STORAGE,
            username=username,
            function_title=function_title,
            provider_name=provider_name,
            extra_sub_path=self.PATH,
        )

    def _key(self, job_id: str) -> str:
        return f"{self._sub_path}/{job_id}{self.ARGUMENTS_FILE_EXTENSION}"

    def get(self, job_id: str) -> Optional[str]:
        """Retrieve arguments for the given job ID from COS."""
        content = self._cos.get_object(self._key(job_id), WorkingDir.USER_STORAGE)
        if content is None:
            logger.info("[get] job_id=%s Arguments not found in COS", job_id)
        return content

    def save(self, job_id: str, arguments: str) -> None:
        """Save arguments for the given job ID to COS."""
        self._cos.put_object(self._key(job_id), arguments, WorkingDir.USER_STORAGE)
        logger.info("[save] job_id=%s Arguments saved to COS", job_id)
