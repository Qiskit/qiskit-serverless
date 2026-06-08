"""Fleets implementation of result storage."""

from __future__ import annotations

import logging
from typing import Optional

from ibm_botocore.exceptions import ClientError

from core.ibm_cloud import get_cos_client
from core.ibm_cloud.code_engine.fleets.utils import build_job_paths
from core.models import Job
from core.services.storage.result_storage import ResultStorage

logger = logging.getLogger("core.FleetsResultStorage")


class FleetsResultStorage(ResultStorage):
    """Handles the storage and retrieval of job results for Fleets jobs via COS."""

    NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}

    def __init__(self, job: Job) -> None:
        if not job.code_engine_project:
            raise ValueError(f"Job '{job.id}' has no CodeEngineProject assigned")

        paths = build_job_paths(job)
        self._job_id = str(job.id)
        self._user_id = job.author.id
        self._project = job.code_engine_project
        self._results_key = paths.cos_results_key
        self._user_bucket = self._load_user_bucket(job)

    def _load_user_bucket(self, job: Job) -> str:
        user_bucket = job.code_engine_project.cos_bucket_user_data_name
        if not user_bucket:
            raise ValueError(
                f"CodeEngineProject '{self._project.project_name}' has no cos_bucket_user_data_name configured"
            )
        return user_bucket

    def get(self) -> Optional[str]:
        """Retrieve the result for this job from COS."""
        try:
            content_bytes = get_cos_client(self._project).get_object_bytes(
                bucket_name=self._user_bucket, key=self._results_key
            )
            logger.info(
                "[get] user_id=%s job_id=%s bucket=%s key=%s | Result retrieved from COS",
                self._user_id,
                self._job_id,
                self._user_bucket,
                self._results_key,
            )
            return content_bytes.decode("utf-8")
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in self.NOT_FOUND_CODES:
                logger.warning(
                    "[get] user_id=%s job_id=%s | Result not found in COS at %s/%s",
                    self._user_id,
                    self._job_id,
                    self._user_bucket,
                    self._results_key,
                )
                return None
            logger.error(
                "[get] user_id=%s job_id=%s | COS error %s: %s",
                self._user_id,
                self._job_id,
                code,
                e,
            )
            return None

    def save(self, result: str) -> None:
        """Not implemented — Fleets results are written by the SDK via RESULTS_PATH."""
        raise NotImplementedError("Fleets results are written by the SDK via RESULTS_PATH")

    def get_url(self) -> Optional[str]:
        """Return a presigned URL for the result, or None if the object does not exist."""
        if not self._object_exists(self._user_bucket, self._results_key):
            return None
        return get_cos_client(self._project).get_presigned_url(
            bucket_name=self._user_bucket,
            key=self._results_key,
        )

    def _object_exists(self, bucket: str, key: str) -> bool:
        try:
            get_cos_client(self._project).head_object(bucket_name=bucket, key=key)
            return True
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in self.NOT_FOUND_CODES:
                return False
            raise
