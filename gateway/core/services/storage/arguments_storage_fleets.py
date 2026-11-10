"""Fleets implementation of arguments storage."""

from __future__ import annotations

import io
import logging

from core.domain.storage_paths import StoragePaths
from core.models import Job
from core.services.storage.arguments_storage import ArgumentsStorage
from core.services.storage.job_storage_paths import get_storage_cos_client

logger = logging.getLogger("core.FleetsArgumentsStorage")


class FleetsArgumentsStorage(ArgumentsStorage):
    """Handles the storage and retrieval of user arguments for Fleets jobs via COS."""

    def __init__(self, job: Job, paths: StoragePaths) -> None:
        """Args:
        job: The job the arguments belong to.
        paths: The job's storage paths: the ones built at creation, before they are saved, or the saved ones.
        """
        self._job = job
        self._paths = paths
        self._job_id = str(job.id)
        self._user_id = job.author.id
        self._bucket = paths.user_bucket
        self._arguments_key = paths.arguments_key

    def save(self, arguments: str) -> None:
        get_storage_cos_client(self._job, self._paths).upload_fileobj(
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
        get_storage_cos_client(self._job, self._paths).delete_object(
            bucket_name=self._bucket, key=self._arguments_key, wait=False
        )
        logger.info(
            "[delete] job_id=%s bucket=%s key=%s Arguments deleted from COS",
            self._job_id,
            self._bucket,
            self._arguments_key,
        )

    def get(self) -> str | None:
        raise NotImplementedError
