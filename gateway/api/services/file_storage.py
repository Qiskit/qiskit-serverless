"""
This file stores the logic to manage the access to data stores
"""
import glob
import logging
import os

from django.conf import settings

from utils import sanitize_file_path

USER_STORAGE = "user"
PROVIDER_STORAGE = "provider"

SUPPORTED_FILE_EXTENSIONS = [".tar", ".h5"]

logger = logging.getLogger("gateway")


class FileStorage:  # pylint: disable=too-few-public-methods
    """
    The main objective of this class is to manage the access of the users to their storage.

    Attributes:
        username (str): storgae user's username
        file_path (str): base user storage file path
    """

    def __init__(
        self,
        username: str,
        working_dir: str,
        function_title: str | None,
        provider_name: str | None,
    ) -> None:
        self.file_path = None
        self.username = username

        if working_dir == USER_STORAGE:
            self.file_path = self.__get_user_path(
                username, function_title, provider_name
            )
        elif working_dir == PROVIDER_STORAGE:
            self.file_path = self.__get_provider_path(function_title, provider_name)

    def __get_user_path(
        self, username: str, function_title: str | None, provider_name: str | None
    ) -> str:
        """
        This method returns the path where the user will store its files

        Args:
            username (str): username folder where files are going to be stored
            function_title (str | None): in case the function is from a
                provider it will identify the function folder
            provider_name (str | None): in case a provider is provided it will
                identify the folder for the specific function

        Returns:
            str: storage path.
                - In case the working_dir would be a provider that path would
                    be: username/provider_name/function_title
                - In case the working_dir would be a user that path would
                    be: username/
        """
        if provider_name is None:
            path = username
        else:
            path = f"{username}/{provider_name}/{function_title}"
        return os.path.join(
            sanitize_file_path(settings.MEDIA_ROOT),
            sanitize_file_path(path),
        )

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
        path = f"{provider_name}/{function_title}"
        return os.path.join(
            sanitize_file_path(settings.MEDIA_ROOT),
            sanitize_file_path(path),
        )

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