"""
This module handle the access to the arguments store
"""

import logging
import os
from typing import Optional

from core.services.storage.path_builder import PathBuilder
from core.services.storage.enums.working_dir import WorkingDir

logger = logging.getLogger("gateway")


class ArgumentsStorage:
    """Handles the storage and retrieval of user arguments."""

    ARGUMENTS_FILE_EXTENSION = ".json"
    PATH = "arguments"
    ENCODING = "utf-8"

    def __init__(self, username: str, function_title: str, provider_name: Optional[str] = None):
        ### In this case arguments are always stored in user folder
        self.sub_path = PathBuilder.sub_path(
            working_dir=WorkingDir.USER_STORAGE,
            username=username,
            function_title=function_title,
            provider_name=provider_name,
            extra_sub_path=self.PATH,
        )
        self.absolute_path = PathBuilder.absolute_path(
            working_dir=WorkingDir.USER_STORAGE,
            username=username,
            function_title=function_title,
            provider_name=provider_name,
            extra_sub_path=self.PATH,
        )

    def _get_arguments_path(self, job_id: str) -> str:
        """Construct the full path for a arguments file."""
        return os.path.join(self.absolute_path, f"{job_id}{self.ARGUMENTS_FILE_EXTENSION}")

    def get(self, job_id: str) -> Optional[str]:
        """
        Retrieve an arguments file for the given job id

        Args:
            job_id (str): the id for the job to get the arguments

        Returns:
            Optional[str]: content of the file
        """
        arguments_path = self._get_arguments_path(job_id)
        if not os.path.exists(arguments_path):
            logger.info(
                "Arguments file for job ID '%s' not found in directory '%s'.",
                job_id,
                arguments_path,
            )
            return None

        try:
            with open(arguments_path, "r", encoding=self.ENCODING) as arguments_file:
                return arguments_file.read()
        except (UnicodeDecodeError, IOError) as e:
            logger.error(
                "Failed to read arguments file for job ID '%s': %s",
                job_id,
                str(e),
            )
            return None

    def save(self, job_id: str, arguments: str) -> None:
        """
        Save the arguments to a file associated with the given job ID.

        Args:
            job_id (str): The unique identifier for the job. This will be used as the base
                name for the arguments file.
            arguments (str): The job arguments to be saved in the file.

        Returns:
            None
        """
        arguments_path = self._get_arguments_path(job_id)
        with open(arguments_path, "w", encoding=self.ENCODING) as arguments_file:
            arguments_file.write(arguments)
        logger.info(
            "Arguments for job ID '%s' successfully saved at '%s'.",
            job_id,
            arguments_path,
        )
