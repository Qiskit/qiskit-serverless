"""Fleets implementation of arguments storage."""

from __future__ import annotations

import io
import logging

from core.domain.storage_paths import StoragePaths
from core.ibm_cloud import get_cos_client
from core.models import Job
from core.services.storage.arguments_storage import ArgumentsStorage
from core.services.storage.job_storage_paths import get_storage_paths

logger = logging.getLogger("core.FleetsArgumentsStorage")


class FleetsArgumentsStorage(ArgumentsStorage):
    """Handles the storage and retrieval of user arguments for Fleets jobs via COS."""

    def __init__(self, job: Job, paths: StoragePaths | None = None) -> None:
        """Args:
        job: The job the arguments belong to.
        paths: The job's storage paths. Given at creation, when they are not saved yet; otherwise they are
            read with :func:`get_storage_paths`.
        """
        if not job.program.code_engine_project:
            raise ValueError(f"Program '{job.program.title}' has no CodeEngineProject assigned")

        self._job_id = str(job.id)
        self._user_id = job.author.id
        self._project = job.program.code_engine_project

        paths = paths or get_storage_paths(job)
        self._bucket = paths.user_bucket
        self._arguments_key = paths.arguments_key

    def save(self, arguments: str) -> None:
        get_cos_client(self._project).upload_fileobj(
            fileobj=io.BytesIO(arguments.encode("utf-8")),
            bucket_name=self._bucket,
            key=self._arguments_key,
        )
        logger.info(
            "[save] user_id=%s job_id=%s bucket=%s key=%s Arguments saved to COS",
            self._user_id,
            self._job_id,
            self._bucket,
            self._arguments_key,
        )

    def delete(self) -> None:
        get_cos_client(self._project).delete_object(bucket_name=self._bucket, key=self._arguments_key, wait=False)
        logger.info(
            "[delete] job_id=%s bucket=%s key=%s Arguments deleted from COS",
            self._job_id,
            self._bucket,
            self._arguments_key,
        )

    def get(self) -> str | None:
        raise NotImplementedError
