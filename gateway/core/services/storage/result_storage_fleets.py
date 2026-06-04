"""Fleets implementation of result storage."""

import logging

from ibm_botocore.exceptions import ClientError

from core.ibm_cloud import get_cos_client
from core.ibm_cloud.code_engine.fleets.utils import build_job_paths
from core.models import Job
from core.services.storage.result_storage import ResultStorage

logger = logging.getLogger("core.FleetsResultStorage")


class FleetsResultStorage(ResultStorage):
    """Handles the storage and retrieval of user job results for Fleets jobs.

    Fleets jobs write results to COS via the RESULTS_PATH mount. This class
    reads them back from the same COS location.
    """

    NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}

    def __init__(self, job: Job) -> None:
        """Initialize the storage with COS path information from the job's program.

        Args:
            job: The Job instance to retrieve results for. If the program has no
                CodeEngineProject assigned, get() will return None.
        """
        self._job_id = str(job.id)
        self._project = job.program.code_engine_project
        if self._project:
            paths = build_job_paths(job)
            self._results_key = paths.cos_results_key
            self._user_bucket = self._project.cos_bucket_user_data_name
        else:
            self._results_key = None
            self._user_bucket = None

    def get(self) -> str | None:
        """Retrieve the result for this job from COS.

        Returns:
            The UTF-8 decoded result string, or None if the result is not
            available (missing project, not-found, or COS error).
        """
        if not self._project or not self._user_bucket or not self._results_key:
            return None
        try:
            content_bytes = get_cos_client(self._project).get_object_bytes(
                bucket_name=self._user_bucket, key=self._results_key
            )
            logger.info(
                "[get] job_id=%s | Result retrieved from COS at %s/%s",
                self._job_id,
                self._user_bucket,
                self._results_key,
            )
            return content_bytes.decode("utf-8")
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in self.NOT_FOUND_CODES:
                logger.warning(
                    "[get] job_id=%s | Result not found in COS at %s/%s",
                    self._job_id,
                    self._user_bucket,
                    self._results_key,
                )
                return None
            logger.error(
                "[get] job_id=%s | COS error %s: %s",
                self._job_id,
                code,
                e,
            )
            return None

    def save(self, result: str) -> None:
        """Not implemented — Fleets results are written by the SDK via RESULTS_PATH.

        Raises:
            NotImplementedError: Always raised. Fleets results are written
                directly to COS by the SDK at RESULTS_PATH.
        """
        raise NotImplementedError("Fleets results are written by the SDK via RESULTS_PATH")
