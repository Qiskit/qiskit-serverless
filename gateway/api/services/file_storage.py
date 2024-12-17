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


SUPPORTED_FILE_EXTENSIONS = [".tar", ".h5"]

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

    @staticmethod
    def is_valid_extension(file_name: str) -> bool:
        """
        This method verifies if the extension of the file is valid.

        Args:
            file_name (str): file name to verify

        Returns:
            bool: True or False if it is valid or not
        """
        return any(
            file_name.endswith(extension) for extension in SUPPORTED_FILE_EXTENSIONS
        )

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

        return sanitize_file_path(path)

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

        return sanitize_file_path(path)

    def get_files(self) -> list[str]:
        """
        This method returns a list of file names following the next rules:
            - Only files with supported extensions are listed
            - It returns only files from a user or a provider file storage

        Returns:
            list[str]: list of file names
        """

        if not os.path.exists(self.file_path):
            logger.warning(
                "Directory %s does not exist for %s.",
                self.file_path,
                self.username,
            )
            return []

        return [
            os.path.basename(path)
            for extension in SUPPORTED_FILE_EXTENSIONS
            for path in glob.glob(f"{self.file_path}/*{extension}")
        ]

    def get_file(self, file_name: str) -> Optional[Tuple[FileWrapper, str, int]]:
        """
        This method returns a file from file_name:
            - Only files with supported extensions are available to download
            - It returns only a file from a user or a provider file storage

        Returns:
            FileWrapper: the file itself
            str: with the type of the file
            int: with the size of the file
        """

        file_name_path = os.path.basename(file_name)
        path_to_file = sanitize_file_path(os.path.join(self.file_path, file_name_path))

        if not os.path.exists(path_to_file):
            logger.warning(
                "Directory %s does not exist for file %s.",
                path_to_file,
                file_name_path,
            )
            return None

        with open(path_to_file, "rb") as file_object:
            file_wrapper = FileWrapper(file_object)

            file_type = mimetypes.guess_type(path_to_file)[0]
            file_size = os.path.getsize(path_to_file)

            return file_wrapper, file_type, file_size

    def remove_file(self, file_name: str) -> bool:
        """
        This method returns a file from file_name:
            - Only files with supported extensions are available to download
            - It returns only a file from a user or a provider file storage

        Returns:
            FileWrapper: the file itself
            str: with the type of the file
            int: with the size of the file
        """

        file_name_path = os.path.basename(file_name)
        path_to_file = sanitize_file_path(os.path.join(self.file_path, file_name_path))

        try:
            os.remove(path_to_file)
        except FileNotFoundError:
            logger.warning(
                "Directory %s does not exist for file %s.",
                path_to_file,
                file_name_path,
            )
            return False
        except OSError as ex:
            logger.warning("OSError: %s.", ex.strerror)
            return False

        return True
