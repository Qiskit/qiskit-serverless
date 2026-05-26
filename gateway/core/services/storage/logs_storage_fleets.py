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
from core.ibm_cloud.code_engine.fleets.utils import build_cos_paths
from core.models import Job
from core.services.storage.logs_storage import LogsStorage

logger = logging.getLogger("core.FleetsLogsStorage")


class FleetsLogsStorage(LogsStorage):
    """Handles the retrieval of logs for Fleets jobs via COS."""

    LOG_FILENAME = "logs.log"
    NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}

    def __init__(self, job: Job) -> None:
        if not job.code_engine_project:
            raise ValueError(f"Job '{job.id}' has no CodeEngineProject assigned")

        self._job_id = str(job.id)
        self._user_id = job.author.id
        self._project = job.code_engine_project

        user_bucket = job.code_engine_project.cos_bucket_user_data_name
        if not user_bucket:
            raise ValueError(
                f"CodeEngineProject '{self._project.project_name}' has no cos_bucket_user_data_name configured"
            )
        self._user_bucket = user_bucket

        paths = build_cos_paths(job)
        self._public_key = paths["user_log_key"]

        if job.program.provider:
            provider_bucket = job.code_engine_project.cos_bucket_provider_data_name
            if not provider_bucket:
                raise ValueError(
                    f"CodeEngineProject '{self._project.project_name}' has no cos_bucket_provider_data_name configured"
                )
            self._provider_bucket: Optional[str] = provider_bucket
            self._private_key: Optional[str] = paths["provider_log_key"]
        else:
            self._provider_bucket = None
            self._private_key = None

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
        if self._private_key is None or self._provider_bucket is None:
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
