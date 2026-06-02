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

"""Fleets implementation of logs storage."""

from __future__ import annotations

import logging
from typing import Optional

from ibm_botocore.exceptions import ClientError

from core.ibm_cloud import get_cos_client
from core.ibm_cloud.code_engine.fleets.utils import build_job_paths
from core.models import Job
from core.services.storage.logs_storage import LogsStorage

logger = logging.getLogger("core.FleetsLogsStorage")


class FleetsLogsStorage(LogsStorage):
    """Handles the retrieval of logs for Fleets jobs via COS."""

    NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}

    def __init__(self, job: Job) -> None:
        if not job.code_engine_project:
            raise ValueError(f"Job '{job.id}' has no CodeEngineProject assigned")

        paths = build_job_paths(job)
        self._job_id = str(job.id)
        self._user_id = job.author.id
        self._project = job.code_engine_project
        self._public_key = paths.cos_user_log_key
        self._private_key: Optional[str] = paths.cos_provider_log_key
        self._user_bucket = self._load_user_bucket(job)
        self._provider_bucket = self._load_provider_bucket(job)

    def _load_provider_bucket(self, job: Job):
        if not job.program.provider:
            return None

        provider_bucket = job.code_engine_project.cos_bucket_provider_data_name
        if not provider_bucket:
            raise ValueError(
                f"CodeEngineProject '{self._project.project_name}' has no cos_bucket_provider_data_name configured"
            )
        return provider_bucket

    def _load_user_bucket(self, job: Job):
        user_bucket = job.code_engine_project.cos_bucket_user_data_name
        if not user_bucket:
            raise ValueError(
                f"CodeEngineProject '{self._project.project_name}' has no cos_bucket_user_data_name configured"
            )
        return user_bucket

    def get_public_logs(self) -> Optional[str]:
        try:
            content_bytes = get_cos_client(self._project).get_object_bytes(
                bucket_name=self._user_bucket, key=self._public_key
            )
            logger.info(
                "[get-public-logs] user_id=%s job_id=%s bucket=%s key=%s Logs retrieved from COS",
                self._user_id,
                self._job_id,
                self._user_bucket,
                self._public_key,
            )
            return content_bytes.decode("utf-8")
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in self.NOT_FOUND_CODES:
                logger.warning(
                    "[get-public-logs] user_id=%s job_id=%s | Log not found in COS at %s/%s",
                    self._user_id,
                    self._job_id,
                    self._user_bucket,
                    self._public_key,
                )
                return None
            logger.error(
                "[get-public-logs] user_id=%s job_id=%s | COS error %s: %s",
                self._user_id,
                self._job_id,
                code,
                e,
            )
            return None

    def get_private_logs(self) -> Optional[str]:
        if self._provider_bucket is None:
            raise RuntimeError("Private logs are only available for provider jobs")
        try:
            content_bytes = get_cos_client(self._project).get_object_bytes(
                bucket_name=self._provider_bucket, key=self._private_key
            )
            logger.info(
                "[get-private-logs] user_id=%s job_id=%s bucket=%s key=%s Logs retrieved from COS",
                self._user_id,
                self._job_id,
                self._provider_bucket,
                self._private_key,
            )
            return content_bytes.decode("utf-8")
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in self.NOT_FOUND_CODES:
                logger.warning(
                    "[get-private-logs] user_id=%s job_id=%s | Log not found in COS at %s/%s",
                    self._user_id,
                    self._job_id,
                    self._provider_bucket,
                    self._private_key,
                )
                return None
            logger.error(
                "[get-private-logs] user_id=%s job_id=%s | COS error %s: %s",
                self._user_id,
                self._job_id,
                code,
                e,
            )
            return None

    def save_public_logs(self, logs: str) -> None:
        raise NotImplementedError

    def save_private_logs(self, logs: str) -> None:
        raise NotImplementedError

    def get_public_logs_url(self) -> Optional[str]:
        if not self._object_exists(self._user_bucket, self._public_key):
            return None
        return get_cos_client(self._project).get_presigned_url(
            bucket_name=self._user_bucket,
            key=self._public_key,
        )

    def get_private_logs_url(self) -> Optional[str]:
        if self._provider_bucket is None:
            raise RuntimeError("Private logs are only available for provider jobs")
        if not self._object_exists(self._provider_bucket, self._private_key):
            return None
        return get_cos_client(self._project).get_presigned_url(
            bucket_name=self._provider_bucket,
            key=self._private_key,
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
