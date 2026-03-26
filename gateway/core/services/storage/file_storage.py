"""
This module handle the access to the files store
"""

import glob
import logging
import mimetypes
import os
from typing import Iterator, Optional, Tuple
from wsgiref.util import FileWrapper

from django.core.files import File

from core.models import Program
from core.services.storage.enums.working_dir import WorkingDir
from core.services.storage.path_builder import PathBuilder
from core.utils import sanitize_file_path

logger = logging.getLogger("gateway")


class FileStorage:
    """
    The main objective of this class is to manage the access of the users to their storage.
    """

    def __init__(
        self,
        username: str,
        working_dir: WorkingDir,
        function: Program,
    ) -> None:
        """
        Initialize FileStorage with a function instance.

        Args:
            username: User's username
            working_dir: Working directory type (USER_STORAGE or PROVIDER_STORAGE)
            function: Program model instance containing title and provider
        """
        function_title = function.title
        provider_name = function.provider.name if function.provider else None

        self.sub_path = PathBuilder.sub_path(
            working_dir=working_dir,
            username=username,
            function_title=function_title,
            provider_name=provider_name,
            extra_sub_path=None,
        )
        self.absolute_path = PathBuilder.absolute_path(
            working_dir=working_dir,
            username=username,
            function_title=function_title,
            provider_name=provider_name,
            extra_sub_path=None,
        )

    def get_files(self) -> list[str]:
        """
        This method returns a list of file names following the next rules:
            - It returns only files from a user or a provider file storage
            - Directories are excluded

        Returns:
            list[str]: list of file names
        """

        return [os.path.basename(path) for path in glob.glob(f"{self.absolute_path}/*") if os.path.isfile(path)]

    def get_file(self, file_name: str) -> Optional[Tuple[FileWrapper, str, int]]:
        """
        This method returns a file from file_name:
            - Only files with supported extensions are available to download
            - It returns only a file from a user or a provider file storage
            - FileWrapper is iterable only from the file system. From mounted COS volumes, use get_file_stream instead

        Args:
            file_name (str): the name of the file to download

        Returns:
            FileWrapper: the file itself
            str: with the type of the file
            int: with the size of the file
        """

        file_name_path = os.path.basename(file_name)
        path_to_file = sanitize_file_path(os.path.join(self.absolute_path, file_name_path))

        if not os.path.exists(path_to_file):
            logger.warning("[get_file] File not found: %s", path_to_file)
            return None

        # We can not use context manager here. Django close the file automatically:
        # https://docs.djangoproject.com/en/5.1/ref/request-response/#fileresponse-objects
        file_wrapper = FileWrapper(open(path_to_file, "rb"))  # pylint: disable=consider-using-with

        file_type = mimetypes.guess_type(path_to_file)[0]
        file_size = os.path.getsize(path_to_file)

        logger.info("[get_file] Reading file: %s", path_to_file)

        return file_wrapper, file_type, file_size

    def get_file_stream(self, file_name: str, chunk_size: int = 65536) -> Optional[Tuple[Iterator[bytes], str, int]]:
        """
        This method returns a streaming generator for a file that we can use for large files

        Args:
            file_name (str): the name of the file to download
            chunk_size (int): bytes per chunk (default 64 KB)

        Returns:
            Iterator[bytes]: generator that yields file chunks
            str: with the type of the file
            int: with the size of the file
        """

        file_name_path = os.path.basename(file_name)
        path_to_file = sanitize_file_path(os.path.join(self.absolute_path, file_name_path))

        if not os.path.exists(path_to_file):
            logger.warning("[get_file_stream] File not found: ", path_to_file)
            return None

        def _stream_chunks():
            with open(path_to_file, "rb") as file_handle:
                while chunk := file_handle.read(chunk_size):
                    yield chunk

        file_type = mimetypes.guess_type(path_to_file)[0]
        file_size = os.path.getsize(path_to_file)

        logger.info("[get_file_stream] Streaming file: %s", path_to_file)

        return _stream_chunks(), file_type, file_size

    def upload_file(self, file: File) -> str:
        """
        This method uploads a file to the specific path:
            - Only files with supported extensions are available to download
            - It returns only a file from a user or a provider file storage

        Args:
            file (django.File): the file to store in the specific path

        Returns:
            str: the path where the file was stored
        """

        file_name = sanitize_file_path(file.name)
        basename = os.path.basename(file_name)
        path_to_file = sanitize_file_path(os.path.join(self.absolute_path, basename))

        with open(path_to_file, "wb+") as destination:
            for chunk in file.chunks():
                destination.write(chunk)

        logger.info("[upload_file] File written: %s", path_to_file)
        return path_to_file

    def remove_file(self, file_name: str) -> bool:
        """
        This method removes a file in the path of file_name

        Args:
            file_name (str): the name of the file to remove

        Returns:
            - True if it was deleted
            - False otherwise
        """

        file_name_path = os.path.basename(file_name)
        path_to_file = sanitize_file_path(os.path.join(self.absolute_path, file_name_path))

        try:
            os.remove(path_to_file)
        except FileNotFoundError:
            logger.warning("[remove_file] File not found: ", path_to_file)
            return False
        except OSError as ex:
            logger.warning("[remove_file] Error deleting %s | OSError: %s", path_to_file, ex.strerror)
            return False

        logger.info("[remove_file] File removed: %s", path_to_file)
        return True
