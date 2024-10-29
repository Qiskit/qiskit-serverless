"""
This file stores the logic to manage the access to data stores
"""
import os

from django.conf import settings

from utils import sanitize_file_path

USER_STORAGE = "user"
PROVIDER_STORAGE = "provider"


class FileStorage:
    def __init__(
        self,
        username: str,
        working_dir: str,
        function_title: str | None,
        provider_name: str | None,
    ) -> None:
        self.file_path = None

        if working_dir == USER_STORAGE:
            self.file_path = self.__get_user_path(
                username, function_title, provider_name
            )
        elif working_dir == PROVIDER_STORAGE:
            self.file_path = self.__get_provider_path(function_title, provider_name)

    def __get_user_path(
        self, username: str, function_title: str, provider_name: str | None
    ) -> str:
        """
        This method returns the path where the user will store its files
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
        """
        path = f"{provider_name}/{function_title}"
        return os.path.join(
            sanitize_file_path(settings.MEDIA_ROOT),
            sanitize_file_path(path),
        )
