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
    """Reads pre-filtered logs written to COS by the in-container wrapper."""

    def __init__(self, job: Job) -> None:
        if not job.code_engine_project:
            raise ValueError(f"Job '{job.id}' has no CodeEngineProject assigned")

        self._job_id = str(job.id)
        self._project = job.code_engine_project

        paths = build_cos_paths(job)
        self._user_bucket = job.code_engine_project.cos_bucket_user_data_name
        self._provider_bucket = job.code_engine_project.cos_bucket_provider_data_name
        self._user_log_key = paths["user_log_key"]
        self._provider_log_key = paths["provider_log_key"]

    def get_public_logs(self) -> Optional[str]:
        if not self._user_bucket:
            return None
        return self._read(self._user_bucket, self._user_log_key)

    def get_private_logs(self) -> Optional[str]:
        if not self._provider_bucket:
            return None
        return self._read(self._provider_bucket, self._provider_log_key)

    def save_public_logs(self, logs: str) -> None:
        raise NotImplementedError("Fleet logs are written directly to COS by the in-container wrapper")

    def save_private_logs(self, logs: str) -> None:
        raise NotImplementedError("Fleet logs are written directly to COS by the in-container wrapper")

    def _read(self, bucket: str, key: str) -> Optional[str]:
        try:
            data = get_cos_client(self._project).get_object_bytes(bucket=bucket, key=key)
            logger.info(
                "[logs-storage] job_id=%s bucket=%s key=%s | Log read from COS",
                self._job_id,
                bucket,
                key,
            )
            return data.decode("utf-8")
        except ClientError:
            logger.info(
                "[logs-storage] job_id=%s bucket=%s key=%s | Log not yet in COS",
                self._job_id,
                bucket,
                key,
            )
            return None
