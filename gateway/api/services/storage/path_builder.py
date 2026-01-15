"""
Builder class to manage the different paths generated in the application
"""

import logging
import os
from typing import Optional

from django.conf import settings

from api.services.storage.enums.working_dir import WorkingDir
from utils import sanitize_file_path


logger = logging.getLogger("gateway")


class PathBuilder:
    """
    This class manages the logic for the user and provider paths generated in the Object Storage
    """

    @staticmethod
    def __get_user_sub_path(
        username: str,
        function_title: str,
        provider_name: Optional[str],
        extra_sub_path: Optional[str],
    ) -> str:
        """
        This method returns the sub-path where the user or the function
        will store files

        Args:
            username (str): IBMiD of the user
            function_title (str): in case the function is from a
                provider it will identify the function folder
            provider_name (str | None): in case a provider is provided it will
                identify the folder for the specific function
            extra_sub_path (str | None): any additional subpath that we want
                to introduce in the path

        Returns:
            str: storage sub-path.
                - In case the function is from a provider that sub-path would
                    be: username/provider_name/function_title/{extra_sub_path}
                - In case the function is from a user that path would
                    be: username/{extra_sub_path}
        """
        if provider_name is None:
            path = os.path.join(username)
        else:
            path = os.path.join(username, provider_name, function_title)

        if extra_sub_path is not None:
            path = os.path.join(path, extra_sub_path)

        return sanitize_file_path(path)

    @staticmethod
    def __get_provider_sub_path(
        function_title: str, provider_name: str, extra_sub_path: Optional[str]
    ) -> str:
        """
        This method returns the provider sub-path where the user
        or the function will store files

        Args:
            function_title (str): in case the function is from a provider
                it will identify the function folder
            provider_name (str): in case a provider is provided
                it will identify the folder for the specific function
            extra_sub_path (str | None): any additional subpath that we want
                to introduce in the path

        Returns:
            str: storage sub-path following the format provider_name/function_title/{extra_sub_path}
        """
        path = os.path.join(provider_name, function_title)

        if extra_sub_path is not None:
            path = os.path.join(path, extra_sub_path)

        return sanitize_file_path(path)

    @staticmethod
    def sub_path(
        working_dir: WorkingDir,
        username: str,
        function_title: str,
        provider_name: Optional[str],
        extra_sub_path: Optional[str],
    ):
        """
        This method returns the relative path for the required interaction.

        Args:
            working_dir (WorkingDir): configuration for the generation of
                the directory
            username (str): IBMiD of the user
            function_title (str): in case the function is from a provider
                it will identify the function folder
            provider_name (str): in case a provider is provided
                it will identify the folder for the specific function
            extra_sub_path (str | None): any additional subpath that we want
                to introduce in the path

        Returns:
            str: storage relative path.
        """

        sub_path = None
        if working_dir is WorkingDir.USER_STORAGE:
            sub_path = PathBuilder.__get_user_sub_path(
                username=username,
                function_title=function_title,
                provider_name=provider_name,
                extra_sub_path=extra_sub_path,
            )
        elif working_dir is WorkingDir.PROVIDER_STORAGE:
            sub_path = PathBuilder.__get_provider_sub_path(
                function_title=function_title,
                provider_name=provider_name,
                extra_sub_path=extra_sub_path,
            )

        return sub_path

    @staticmethod
    def absolute_path(
        working_dir: WorkingDir,
        username: str,
        function_title: str,
        provider_name: Optional[str],
        extra_sub_path: Optional[str],
    ) -> str:
        """
        This method returns the aboslute path for the required interaction
        and it creates it if it doesn't exist.

        Args:
            working_dir (WorkingDir): configuration for the generation of
                the directory
            username (str): IBMiD of the user
            function_title (str): in case the function is from a provider
                it will identify the function folder
            provider_name (str): in case a provider is provided
                it will identify the folder for the specific function
            extra_sub_path (str | None): any additional subpath that we want
                to introduce in the path

        Returns:
            str: storage relative path.
        """

        sub_path = PathBuilder.sub_path(
            working_dir=working_dir,
            username=username,
            function_title=function_title,
            provider_name=provider_name,
            extra_sub_path=extra_sub_path,
        )
        path = os.path.join(settings.MEDIA_ROOT, sub_path)
        sanitized_path = sanitize_file_path(path)

        # Create directory if it doesn't exist
        if not os.path.exists(sanitized_path):
            os.makedirs(sanitized_path, exist_ok=True)
            logger.debug("Path %s was created.", sanitized_path)

        return sanitized_path
