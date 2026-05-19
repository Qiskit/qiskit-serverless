"""Fleets implementation of arguments storage."""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING, Optional

from core.models import Job
from core.services.storage.arguments_storage import ArgumentsStorage

if TYPE_CHECKING:
    from core.ibm_cloud.code_engine.fleets.cos import JobCOS

logger = logging.getLogger("core.FleetsArgumentsStorage")


class FleetsArgumentsStorage(ArgumentsStorage):
    """Handles the storage and retrieval of user arguments for Fleets jobs via COS."""

    ARGUMENTS_FILENAME = "arguments.json"

    def __init__(self, job: Job) -> None:
        if not job.code_engine_project:
            raise ValueError(f"Job '{job.id}' has no CodeEngineProject assigned")

        self._job_id = str(job.id)
        self._project = job.code_engine_project

        bucket = job.code_engine_project.cos_bucket_user_data_name
        if not bucket:
            raise ValueError(
                f"CodeEngineProject '{self._project.project_name}' has no cos_bucket_user_data_name configured"
            )
        self._bucket = bucket

        username = job.author.username
        provider_name = job.program.provider.name if job.program.provider else None
        program_title = job.program.title

        if provider_name:
            path = f"users/{username}/provider_functions/{provider_name}/{program_title}/jobs/{self._job_id}"
        else:
            path = f"users/{username}/custom_functions/{program_title}/jobs/{self._job_id}"

        self._arguments_key = f"{path}/{self.ARGUMENTS_FILENAME}"

    def _get_cos(self) -> "JobCOS":
        from core.ibm_cloud import get_cos_client  # pylint: disable=import-outside-toplevel

        return get_cos_client(self._project)

    def save(self, arguments: str) -> None:
        self._get_cos().upload_fileobj(
            fileobj=io.BytesIO(arguments.encode("utf-8")),
            bucket_name=self._bucket,
            key=self._arguments_key,
        )
        logger.info(
            "Arguments for job [%s] saved to COS at %s/%s",
            self._job_id,
            self._bucket,
            self._arguments_key,
        )

    def get(self) -> Optional[str]:
        try:
            data = self._get_cos().get_object_bytes(bucket_name=self._bucket, key=self._arguments_key)
            return data.decode("utf-8") if data else None
        except Exception:  # pylint: disable=broad-exception-caught
            logger.warning("Could not retrieve arguments for job [%s] from COS", self._job_id)
            return None
