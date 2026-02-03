"""
This file stores the logic to manage the access to data stores
"""

import glob
import logging
import mimetypes
import os
from typing import Optional, Tuple
from wsgiref.util import FileWrapper

from django.core.files import File

from api.models import Program
from api.services.storage.enums.working_dir import WorkingDir
from api.services.storage.path_builder import PathBuilder
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

        return [
            os.path.basename(path)
            for path in glob.glob(f"{self.absolute_path}/*")
            if os.path.isfile(path)
        ]

    def get_file(self, file_name: str) -> Optional[Tuple[FileWrapper, str, int]]:
        """
        This method returns a file from file_name:
            - Only files with supported extensions are available to download
            - It returns only a file from a user or a provider file storage

        Args:
            file_name (str): the name of the file to download

        Returns:
            FileWrapper: the file itself
            str: with the type of the file
            int: with the size of the file
        """

        file_name_path = os.path.basename(file_name)
        path_to_file = sanitize_file_path(
            os.path.join(self.absolute_path, file_name_path)
        )

        if not os.path.exists(path_to_file):
            logger.warning(
                "File %s not found in %s.",
                file_name_path,
                path_to_file,
            )
            return None

        # We can not use context manager here. Django close the file automatically:
        # https://docs.djangoproject.com/en/5.1/ref/request-response/#fileresponse-objects
        file_wrapper = FileWrapper(
            open(path_to_file, "rb")  # pylint: disable=consider-using-with
        )

        file_type = mimetypes.guess_type(path_to_file)[0]
        file_size = os.path.getsize(path_to_file)

        return file_wrapper, file_type, file_size

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

        return path_to_file

    def remove_file(self, file_name: str) -> bool:
        """
        This method remove a file in the path of file_name

        Args:
            file_name (str): the name of the file to remove

        Returns:
            - True if it was deleted
            - False otherwise
        """

        file_name_path = os.path.basename(file_name)
        path_to_file = sanitize_file_path(
            os.path.join(self.absolute_path, file_name_path)
        )

        try:
            os.remove(path_to_file)
        except FileNotFoundError:
            logger.warning(
                "File %s not found in %s.",
                file_name_path,
                path_to_file,
            )
            return False
        except OSError as ex:
            logger.warning("OSError: %s.", ex.strerror)
            return False

        return True
