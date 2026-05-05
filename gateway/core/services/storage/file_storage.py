"""
This module handle the access to the files store
"""

import io
import logging
import mimetypes
from typing import Iterator, Optional, Tuple

from django.core.files import File

from core.models import Program
from core.services.storage.abstract_cos_client import AbstractCOSClient
from core.services.storage.enums.working_dir import WorkingDir
from core.services.storage.path_builder import PathBuilder

logger = logging.getLogger("core.FileStorage")


class FileStorage:
    """
    Manages access to user and provider file storage via COS.
    """

    def __init__(
        self,
        username: str,
        working_dir: WorkingDir,
        function: Program,
        cos: AbstractCOSClient,
    ) -> None:
        function_title = function.title
        provider_name = function.provider.name if function.provider else None

        self._working_dir = working_dir
        self._cos = cos
        self.sub_path = PathBuilder.sub_path(
            working_dir=working_dir,
            username=username,
            function_title=function_title,
            provider_name=provider_name,
            extra_sub_path=None,
        )

    def _file_path(self, file_name: str) -> str:
        return f"{self.sub_path}/{file_name}"

    def get_files(self) -> list[str]:
        """Return a list of file names directly under the storage prefix (non-recursive)."""
        prefix = self.sub_path + "/"
        object_paths = self._cos.list_objects(prefix, self._working_dir)
        result = []
        for obj_path in object_paths:
            relative = obj_path[len(prefix) :]
            # Exclude nested paths and empty segments
            if relative and "/" not in relative:
                result.append(relative)
        return result

    def get_file(self, file_name: str) -> Optional[Tuple[io.BytesIO, str, int]]:
        """
        Download a file from COS.

        Returns:
            (BytesIO, content_type, size) or None if not found
        """
        content = self._cos.get_object_bytes(self._file_path(file_name), self._working_dir)
        if content is None:
            logger.warning("[get_file] File not found: %s", self._file_path(file_name))
            return None

        content_type = mimetypes.guess_type(file_name)[0]
        logger.info("[get_file] Downloaded file: %s", self._file_path(file_name))
        return io.BytesIO(content), content_type, len(content)

    def get_file_stream(self, file_name: str, chunk_size: int = 65536) -> Optional[Tuple[Iterator[bytes], str, int]]:
        """
        Stream a file from COS in chunks.

        Returns:
            (Iterator[bytes], content_type, size) or None if not found
        """
        content = self._cos.get_object_for_stream(self._file_path(file_name), self._working_dir)
        if content is None:
            logger.warning("[get_file_stream] File not found: %s", self._file_path(file_name))
            return None

        def _stream_chunks():
            for chunk in content.iter_chunks(chunk_size=chunk_size):
                if chunk:
                    yield chunk

        content_type = mimetypes.guess_type(file_name)[0]
        logger.info("[get_file_stream] Streaming file: %s", self._file_path(file_name))
        return _stream_chunks(), content_type, len(content)

    def upload_file(self, file: File) -> str:
        """
        Upload a file to COS.

        Returns:
            The COS key where the file was stored.
        """
        file_name = file.name
        key = self._file_path(file_name)
        content = b"".join(file.chunks())
        self._cos.put_object_bytes(key, content, self._working_dir)
        logger.info("[upload_file] File uploaded: %s", key)
        return key

    def remove_file(self, file_name: str) -> bool:
        """
        Remove a file from COS.

        Returns:
            True if deleted, False otherwise.
        """
        success = self._cos.delete_object(self._file_path(file_name), self._working_dir)
        if success:
            logger.info("[remove_file] File removed: %s", self._file_path(file_name))
        else:
            logger.warning("[remove_file] File not found or delete failed: %s", self._file_path(file_name))
        return success
