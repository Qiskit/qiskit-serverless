"""
This file stores the logic to manage the access to data stores
"""
import glob
import logging
import mimetypes
import os
from enum import Enum
from typing import Optional, Tuple
from wsgiref.util import FileWrapper

from django.conf import settings
from django.core.files import File

from utils import sanitize_file_path


class WorkingDir(Enum):
    """
    This Enum has the values:
        USER_STORAGE
        PROVIDER_STORAGE

    Both values are being used to identify in
        FileStorage service the path to be used
    """

    USER_STORAGE = 1
    PROVIDER_STORAGE = 2


logger = logging.getLogger("gateway")


class FileStorage:  # pylint: disable=too-few-public-methods
    """
    The main objective of this class is to manage the access of the users to their storage.

    Attributes:
        username (str): storgae user's username
        working_dir (WorkingDir(Enum)): working directory
        function_title (str): title of the function in case is needed to build the path
        provider_name (str | None): name of the provider in caseis needed to build the path
    """

    def __init__(
        self,
        username: str,
        working_dir: WorkingDir,
        function_title: str,
        provider_name: str | None,
    ) -> None:
        self.file_path = None
        self.username = username

        if working_dir is WorkingDir.USER_STORAGE:
            self.file_path = self.__get_user_path(function_title, provider_name)
        elif working_dir is WorkingDir.PROVIDER_STORAGE:
            self.file_path = self.__get_provider_path(function_title, provider_name)

    def __get_user_path(self, function_title: str, provider_name: str | None) -> str:
        """
        This method returns the path where the user will store its files

        Args:
            function_title (str): in case the function is from a
                provider it will identify the function folder
            provider_name (str | None): in case a provider is provided it will
                identify the folder for the specific function

        Returns:
            str: storage path.
                - In case the function is from a provider that path would
                    be: username/provider_name/function_title
                - In case the function is from a user that path would
                    be: username/
        """
        if provider_name is None:
            path = os.path.join(settings.MEDIA_ROOT, self.username)
        else:
            path = os.path.join(
                settings.MEDIA_ROOT, self.username, provider_name, function_title
            )

        sanitized_path = sanitize_file_path(path)

        # Create directory if it doesn't exist
        if not os.path.exists(sanitized_path):
            os.makedirs(sanitized_path, exist_ok=True)
            logger.debug("Path %s was created.", sanitized_path)

        return sanitized_path

    def __get_provider_path(self, function_title: str, provider_name: str) -> str:
        """
        This method returns the provider path where the user will store its files

        Args:
            function_title (str): in case the function is from a provider
                it will identify the function folder
            provider_name (str): in case a provider is provided
                it will identify the folder for the specific function

        Returns:
            str: storage path following the format provider_name/function_title/
        """
        path = os.path.join(settings.MEDIA_ROOT, provider_name, function_title)

        sanitized_path = sanitize_file_path(path)

        # Create directory if it doesn't exist
        if not os.path.exists(sanitized_path):
            os.makedirs(sanitized_path, exist_ok=True)
            logger.debug("Path %s was created.", sanitized_path)

        return sanitized_path

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
            for path in glob.glob(f"{self.file_path}/*")
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
        path_to_file = sanitize_file_path(os.path.join(self.file_path, file_name_path))

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
        This method upload a file to the specific path:
            - Only files with supported extensions are available to download
            - It returns only a file from a user or a provider file storage

        Args:
            file (django.File): the file to store in the specific path

        Returns:
            str: the path where the file was stored
        """

        file_name = sanitize_file_path(file.name)
        basename = os.path.basename(file_name)
        path_to_file = sanitize_file_path(os.path.join(self.file_path, basename))

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
        path_to_file = sanitize_file_path(os.path.join(self.file_path, file_name_path))

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
