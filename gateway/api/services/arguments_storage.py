"""
This module handle the access to the arguments store
"""
import logging
import os
from typing import Optional
from django.conf import settings

logger = logging.getLogger("gateway")


class ArgumentsStorage:
    """Handles the storage and retrieval of user arguments."""

    ARGUMENTS_FILE_EXTENSION = ".json"
    ENCODING = "utf-8"

    def __init__(
        self, username: str, function_title: str, provider_name: Optional[str]
    ):
        # We need to use the same path as the FileStorage here
        # because it is attached the volume in the docker image
        if provider_name is None:
            self.user_arguments_directory = os.path.join(
                settings.MEDIA_ROOT, username, "arguments"
            )
        else:
            self.user_arguments_directory = os.path.join(
                settings.MEDIA_ROOT,
                username,
                provider_name,
                function_title,
                "arguments",
            )

        os.makedirs(self.user_arguments_directory, exist_ok=True)

    def _get_arguments_path(self, job_id: str) -> str:
        """Construct the full path for a arguments file."""
        return os.path.join(
            self.user_arguments_directory, f"{job_id}{self.ARGUMENTS_FILE_EXTENSION}"
        )

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
                self.user_arguments_directory,
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
