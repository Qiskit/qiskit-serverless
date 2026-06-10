"""Fleets implementation of arguments storage."""

from __future__ import annotations

import io
import logging

from core.ibm_cloud import get_cos_client
from core.ibm_cloud.code_engine.fleets.utils import build_job_paths
from core.models import Job
from core.services.storage.arguments_storage import ArgumentsStorage

logger = logging.getLogger("core.FleetsArgumentsStorage")


class FleetsArgumentsStorage(ArgumentsStorage):
    """Handles the storage and retrieval of user arguments for Fleets jobs via COS."""

    ARGUMENTS_FILENAME = "arguments.json"

    def __init__(self, job: Job) -> None:
        if not job.program.code_engine_project:
            raise ValueError(f"Program '{job.program.title}' has no CodeEngineProject assigned")

        self._job_id = str(job.id)
        self._user_id = job.author.id
        self._project = job.program.code_engine_project

        bucket = self._project.cos_bucket_user_data_name
        if not bucket:
            raise ValueError(
                f"CodeEngineProject '{self._project.project_name}' has no cos_bucket_user_data_name configured"
            )
        self._bucket = bucket

        paths = build_job_paths(job)
        self._arguments_key = paths.cos_user_job_prefix + "/" + self.ARGUMENTS_FILENAME

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

    def get(self) -> str | None:
        raise NotImplementedError
