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

"""Admin-oriented service to list all storage files for a Job."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from core.ibm_cloud import get_cos_client
from core.ibm_cloud.code_engine.fleets.utils import build_job_paths
from core.models import Program
from core.services.storage.arguments_storage_ray import RayArgumentsStorage
from core.services.storage.file_storage_ray import FileStorageRay
from core.services.storage.logs_storage_ray import RayLogsStorage
from core.services.storage.result_storage_ray import RayResultStorage

if TYPE_CHECKING:
    from core.models import Job

logger = logging.getLogger("gateway.job_file_explorer")


@dataclass
class FileEntry:
    """A single storage file with metadata."""

    name: str
    full_key: str
    size_bytes: int
    last_modified: datetime | None
    bucket_or_path: str


@dataclass
class FileGroup:
    """A named category of storage files."""

    category: str
    files: list[FileEntry]


class JobFileExplorer:
    """Return all storage files for a Job, grouped by category."""

    def explore(self, job: Job) -> list[FileGroup]:
        """Return all storage files for the given job, grouped by category."""
        if job.program.runner == Program.FLEETS:
            return self._explore_fleets(job)
        return self._explore_ray(job)

    def _explore_fleets(self, job: Job) -> list[FileGroup]:
        paths = build_job_paths(job)
        project = job.program.code_engine_project
        cos = get_cos_client(project)
        user_bucket = project.cos_bucket_user_data_name
        groups: list[FileGroup] = []

        group = self._list_cos_group("Data Files", cos, user_bucket, paths.cos_user_function_prefix)
        if group:
            groups.append(group)

        group = self._list_cos_group("Job Files", cos, user_bucket, paths.cos_user_job_prefix)
        if group:
            groups.append(group)

        if paths.cos_provider_function_prefix:
            provider_bucket = project.cos_bucket_provider_data_name
            group = self._list_cos_group("Provider Data", cos, provider_bucket, paths.cos_provider_function_prefix)
            if group:
                groups.append(group)

        if paths.cos_provider_job_prefix:
            provider_bucket = project.cos_bucket_provider_data_name
            group = self._list_cos_group("Provider Job Files", cos, provider_bucket, paths.cos_provider_job_prefix)
            if group:
                groups.append(group)

        return groups

    def _list_cos_group(self, category: str, cos, bucket: str, prefix: str) -> FileGroup | None:
        try:
            objects = cos.list_with_metadata(bucket_name=bucket, prefix=prefix)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.error(
                "[job-file-explorer] Failed to list %s at %s/%s",
                category,
                bucket,
                prefix,
                exc_info=True,
            )
            return None
        if not objects:
            return None
        files = [self._cos_entry(obj, bucket) for obj in objects]
        return FileGroup(category=category, files=files)

    @staticmethod
    def _cos_entry(obj: dict, bucket: str) -> FileEntry:
        key = obj["key"]
        return FileEntry(
            name=key.rsplit("/", 1)[-1],
            full_key=key,
            size_bytes=obj.get("size", 0),
            last_modified=obj.get("last_modified"),
            bucket_or_path=bucket,
        )

    def _explore_ray(self, job: Job) -> list[FileGroup]:
        username = job.author.username
        file_storage = FileStorageRay(username, job.program)
        result_storage = RayResultStorage(job)
        logs_storage = RayLogsStorage(job)
        args_storage = RayArgumentsStorage(job)

        groups: list[FileGroup] = []

        data_files = self._scan_dir(file_storage.public_path, file_storage.public_sub_path)
        if data_files:
            groups.append(FileGroup(category="Data Files", files=data_files))

        entry = self._stat_entry(result_storage.result_file_path, os.path.join(username, "results"))
        if entry:
            groups.append(FileGroup(category="Results", files=[entry]))

        log_path = logs_storage.log_file_path(logs_storage.public_log_dir)
        entry = self._stat_entry(log_path, logs_storage.public_log_dir)
        if entry:
            groups.append(FileGroup(category="Logs", files=[entry]))

        args_path = os.path.join(args_storage.absolute_path, f"{job.id}.json")
        entry = self._stat_entry(args_path, args_storage.sub_path)
        if entry:
            groups.append(FileGroup(category="Arguments", files=[entry]))

        if logs_storage.private_log_dir:
            priv_log_path = logs_storage.log_file_path(logs_storage.private_log_dir)
            entry = self._stat_entry(priv_log_path, logs_storage.private_log_dir)
            if entry:
                groups.append(FileGroup(category="Private Logs", files=[entry]))

        return groups

    @staticmethod
    def _stat_entry(path: str, base_sub: str) -> FileEntry | None:
        if not os.path.isfile(path):
            return None
        try:
            st = os.stat(path)
            return FileEntry(
                name=os.path.basename(path),
                full_key=path,
                size_bytes=st.st_size,
                last_modified=datetime.fromtimestamp(st.st_mtime),
                bucket_or_path=base_sub,
            )
        except OSError:
            logger.error("[job-file-explorer] Cannot stat %s", path, exc_info=True)
            return None

    @staticmethod
    def _scan_dir(directory: str, base_sub: str) -> list[FileEntry]:
        if not os.path.isdir(directory):
            return []
        entries: list[FileEntry] = []
        try:
            with os.scandir(directory) as it:
                for item in it:
                    if not item.is_file():
                        continue
                    st = item.stat()
                    entries.append(
                        FileEntry(
                            name=item.name,
                            full_key=item.path,
                            size_bytes=st.st_size,
                            last_modified=datetime.fromtimestamp(st.st_mtime),
                            bucket_or_path=base_sub,
                        )
                    )
        except OSError:
            logger.error("[job-file-explorer] Cannot scan dir %s", directory, exc_info=True)
        return entries
