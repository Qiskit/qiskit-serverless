"""Fleets implementation of result storage."""

from __future__ import annotations

import logging
from typing import Optional

from core.ibm_cloud import get_cos_client
from core.ibm_cloud.code_engine.fleets.utils import build_job_paths
from core.models import Job
from core.services.storage.result_storage import ResultStorage

logger = logging.getLogger("core.FleetsResultStorage")


class FleetsResultStorage(ResultStorage):
    """Handles the storage and retrieval of user job results for Fleets jobs via COS."""

    def __init__(self, job: Job) -> None:
        self._job_id = str(job.id)
        if not job.code_engine_project or not job.code_engine_project.cos_bucket_user_data_name:
            self._project = None
            self._bucket = None
            self._results_key = None
        else:
            self._project = job.code_engine_project
            paths = build_job_paths(job)
            self._bucket = job.code_engine_project.cos_bucket_user_data_name
            self._results_key = paths.cos_results_key

    def get(self) -> Optional[str]:
        """Retrieve the result for this job from COS."""
        if not self._project:
            return None
        try:
            data = get_cos_client(self._project).get_object_bytes(
                bucket_name=self._bucket,
                key=self._results_key,
            )
            if data:
                logger.info(
                    "[get] job_id=%s bucket=%s key=%s Result retrieved from COS",
                    self._job_id,
                    self._bucket,
                    self._results_key,
                )
                return data.decode("utf-8")
            return None
        except Exception as ex:  # pylint: disable=broad-exception-caught
            logger.warning("[get] job_id=%s Failed to retrieve result from COS: %s", self._job_id, ex)
            return None

    def save(self, result: str) -> None:
        """Persist the result for this job."""
        raise NotImplementedError
