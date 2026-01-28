"""
Builder class to manage the different paths generated in the application
"""

import logging
import os
from typing import Optional, NamedTuple

from django.conf import settings

from utils import sanitize_file_path

logger = logging.getLogger("gateway")


class StoragePath(NamedTuple):
    """Immutable. Storage path information.
    sub_path: Relative path within the storage system
    absolute_path: Full absolute path on the filesystem. It can be used to read/write files.
    """

    sub_path: str
    absolute_path: str


class PathBuilder:
    """
    This class manages the logic for the user and provider paths generated in the Object Storage
    """

    @staticmethod
    def get_user_path(
        username: str,
        function_title: str,
        provider_name: Optional[str],
        extra_sub_path: Optional[str] = None,
    ) -> StoragePath:
        """
        Returns paths for user storage.

        Args:
            username (str): IBMiD of the user
            function_title (str): in case the function is from a
                provider it will identify the function folder
            provider_name (str | None): in case a provider is provided it will
                identify the folder for the specific function
            extra_sub_path (str | None): any additional subpath that we want
                to introduce in the path

        Returns:
            StoragePath: storage paths.
                - In case the function is from a provider that sub_path would
                    be: username/provider_name/function_title/{extra_sub_path}
                - In case the function is from a user that sub_path would
                    be: username/{extra_sub_path}
        """
        if provider_name is None:
            path = os.path.join(username)
        else:
            path = os.path.join(username, provider_name, function_title)

        if extra_sub_path is not None:
            path = os.path.join(path, extra_sub_path)

        sub_path = sanitize_file_path(path)
        absolute_path = PathBuilder._create_absolute_path(sub_path)

        return StoragePath(sub_path=sub_path, absolute_path=absolute_path)

    @staticmethod
    def get_provider_path(
        function_title: str,
        provider_name: str,
        extra_sub_path: Optional[str] = None,
    ) -> StoragePath:
        """
        Returns paths for provider storage.

        Args:
            function_title (str): in case the function is from a provider
                it will identify the function folder
            provider_name (str): in case a provider is provided
                it will identify the folder for the specific function
            extra_sub_path (str | None): any additional subpath that we want
                to introduce in the path

        Returns:
            StoragePath: storage paths with sub_path following the format
                provider_name/function_title/{extra_sub_path}
        """
        path = os.path.join(provider_name, function_title)

        if extra_sub_path is not None:
            path = os.path.join(path, extra_sub_path)

        sub_path = sanitize_file_path(path)
        absolute_path = PathBuilder._create_absolute_path(sub_path)

        return StoragePath(sub_path=sub_path, absolute_path=absolute_path)

    @staticmethod
    def _create_absolute_path(sub_path: str) -> str:
        """
        Creates the absolute path from a sub_path and ensures the directory exists.

        Args:
            sub_path (str): the relative sub-path

        Returns:
            str: the absolute path on the filesystem
        """
        path = os.path.join(settings.MEDIA_ROOT, sub_path)
        sanitized_path = sanitize_file_path(path)

        # Create directory if it doesn't exist
        if not os.path.exists(sanitized_path):
            os.makedirs(sanitized_path, exist_ok=True)
            logger.debug("Path %s was created.", sanitized_path)

        return sanitized_path
