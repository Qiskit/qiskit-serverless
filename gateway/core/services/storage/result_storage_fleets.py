# This code is part of a Qiskit project.
#
# (C) IBM 2026
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

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
            job: The Job instance to retrieve results for.
        """
        self._job_id = str(job.id)
        self._user_id = job.author.id
        self._project = job.program.code_engine_project
        paths = build_job_paths(job)
        self._results_key = paths.cos_results_key
        self._user_bucket = self._load_user_bucket()

    def _load_user_bucket(self) -> str:
        """Return the user data bucket name, raising ValueError if not configured."""
        user_bucket = self._project.cos_bucket_user_data_name
        if not user_bucket:
            raise ValueError(
                f"CodeEngineProject '{self._project.project_name}' has no cos_bucket_user_data_name configured"
            )
        return user_bucket

    def get(self) -> str | None:
        """Retrieve the result for this job from COS.

        Returns:
            The UTF-8 decoded result string, or None if the result is not
            available (missing project, not-found, or COS error).
        """
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
                    "[get] user_id=%s job_id=%s | Result not found in COS at %s/%s (code=%s)",
                    self._user_id,
                    self._job_id,
                    self._user_bucket,
                    self._results_key,
                    code,
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
        except UnicodeDecodeError as e:
            logger.error(
                "[get] user_id=%s job_id=%s | Failed to decode result: %s",
                self._user_id,
                self._job_id,
                e,
            )
            return None

    def save(self, result: str) -> None:
        """Not implemented — Fleets results are written by the SDK via RESULTS_PATH.

        Args:
            result: Unused. Present only to satisfy the abstract interface.

        Raises:
            NotImplementedError: Always raised. Fleets results are written
                directly to COS by the SDK at RESULTS_PATH.
        """
        raise NotImplementedError("Fleets results are written by the SDK via RESULTS_PATH")

    def get_url(self) -> str | None:
        """Return a presigned URL for the result, or None if the object does not exist."""
        if not self._object_exists(self._user_bucket, self._results_key):
            return None
        return get_cos_client(self._project).get_presigned_url(
            bucket_name=self._user_bucket,
            key=self._results_key,
        )

    def _object_exists(self, bucket: str, key: str) -> bool:
        """Return True if the COS object exists, False on 404/NoSuchKey, re-raise on other errors."""
        try:
            get_cos_client(self._project).head_object(bucket_name=bucket, key=key)
            return True
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in self.NOT_FOUND_CODES:
                return False
            raise
