"""Admin-oriented service to list all storage files for a Job."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from django.conf import settings

from core.ibm_cloud import get_cos_client
from core.services.storage.enums.working_dir import WorkingDir
from core.services.storage.path_builder import PathBuilder

if TYPE_CHECKING:
    from core.models import Job

logger = logging.getLogger("gateway.job_file_explorer")


@dataclass
class FileEntry:
    name: str
    full_key: str
    size_bytes: int
    last_modified: datetime | None
    bucket_or_path: str


@dataclass
class FileGroup:
    category: str
    files: list[FileEntry]


class JobFileExplorer:
    """Return all storage files for a Job, grouped by category."""

    def explore(self, job: Job) -> list[FileGroup]:
        from core.models import Program

        if job.program.runner == Program.FLEETS:
            return self._explore_fleets(job)
        return self._explore_ray(job)

    # ------------------------------------------------------------------
    # Fleets (COS)
    # ------------------------------------------------------------------

    def _explore_fleets(self, job: Job) -> list[FileGroup]:
        project = job.program.code_engine_project
        cos = get_cos_client(project)
        user_bucket = project.cos_bucket_user_data_name
        username = job.author.username
        program_title = job.program.title
        job_id = str(job.id)
        provider = job.program.provider

        groups: list[FileGroup] = []

        if provider:
            provider_name = provider.name
            data_prefix = f"users/{username}/provider_functions/{provider_name}/{program_title}/data"
            job_prefix = f"users/{username}/provider_functions/{provider_name}/{program_title}/jobs/{job_id}/"
            provider_data_prefix = f"providers/{provider_name}/{program_title}/data"
            provider_job_prefix = f"providers/{provider_name}/{program_title}/jobs/{job_id}/"
        else:
            data_prefix = f"users/{username}/custom_functions/{program_title}/data"
            job_prefix = f"users/{username}/custom_functions/{program_title}/jobs/{job_id}/"
            provider_data_prefix = None
            provider_job_prefix = None

        # Data files
        group = self._list_cos_group("Data Files", cos, user_bucket, data_prefix)
        if group:
            groups.append(group)

        # Job artifacts — one prefix, split by filename suffix
        try:
            artifacts = cos.list_with_metadata(bucket_name=user_bucket, prefix=job_prefix)
        except Exception:
            logger.error(
                "[job-file-explorer] job_id=%s | Failed to list job artifacts at %s/%s",
                job.id,
                user_bucket,
                job_prefix,
                exc_info=True,
            )
            artifacts = []

        for category, suffix in [
            ("Results", "results.json"),
            ("Logs", "logs.log"),
            ("Arguments", "arguments.json"),
        ]:
            files = [self._cos_entry(obj, user_bucket) for obj in artifacts if obj["key"].endswith(suffix)]
            if files:
                groups.append(FileGroup(category=category, files=files))

        # Provider data and private logs
        if provider_data_prefix:
            provider_bucket = project.cos_bucket_provider_data_name
            group = self._list_cos_group("Provider Data", cos, provider_bucket, provider_data_prefix)
            if group:
                groups.append(group)

        if provider_job_prefix:
            provider_bucket = project.cos_bucket_provider_data_name
            group = self._list_cos_group("Private Logs", cos, provider_bucket, provider_job_prefix)
            if group:
                groups.append(group)

        return groups

    def _list_cos_group(self, category: str, cos, bucket: str, prefix: str) -> FileGroup | None:
        try:
            objects = cos.list_with_metadata(bucket_name=bucket, prefix=prefix)
        except Exception:
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

    # ------------------------------------------------------------------
    # Ray (filesystem)
    # ------------------------------------------------------------------

    def _explore_ray(self, job: Job) -> list[FileGroup]:
        username = job.author.username
        function_title = job.program.title
        provider_name = job.program.provider.name if job.program.provider else None
        job_id = str(job.id)
        media_root = settings.MEDIA_ROOT

        groups: list[FileGroup] = []

        # Data files — user storage root for this function
        data_sub = PathBuilder.sub_path(
            working_dir=WorkingDir.USER_STORAGE,
            username=username,
            function_title=function_title,
            provider_name=provider_name,
            extra_sub_path=None,
        )
        data_dir = os.path.join(media_root, data_sub)
        data_files = self._scan_dir(data_dir, data_sub)
        if data_files:
            groups.append(FileGroup(category="Data Files", files=data_files))

        # Results — hardcoded path used by RayResultStorage
        results_path = os.path.join(media_root, username, "results", f"{job_id}.json")
        entry = self._stat_entry(results_path, os.path.join(username, "results"))
        if entry:
            groups.append(FileGroup(category="Results", files=[entry]))

        # Logs — PathBuilder USER_STORAGE with extra_sub_path="logs"
        logs_sub = PathBuilder.sub_path(
            working_dir=WorkingDir.USER_STORAGE,
            username=username,
            function_title=function_title,
            provider_name=provider_name,
            extra_sub_path="logs",
        )
        logs_path = os.path.join(media_root, logs_sub, f"{job_id}.log")
        entry = self._stat_entry(logs_path, logs_sub)
        if entry:
            groups.append(FileGroup(category="Logs", files=[entry]))

        # Arguments — PathBuilder USER_STORAGE with extra_sub_path="arguments"
        args_sub = PathBuilder.sub_path(
            working_dir=WorkingDir.USER_STORAGE,
            username=username,
            function_title=function_title,
            provider_name=provider_name,
            extra_sub_path="arguments",
        )
        args_path = os.path.join(media_root, args_sub, f"{job_id}.json")
        entry = self._stat_entry(args_path, args_sub)
        if entry:
            groups.append(FileGroup(category="Arguments", files=[entry]))

        # Private logs for provider jobs
        if provider_name:
            priv_sub = PathBuilder.sub_path(
                working_dir=WorkingDir.PROVIDER_STORAGE,
                username=username,
                function_title=function_title,
                provider_name=provider_name,
                extra_sub_path="logs",
            )
            priv_path = os.path.join(media_root, priv_sub, f"{job_id}.log")
            entry = self._stat_entry(priv_path, priv_sub)
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
