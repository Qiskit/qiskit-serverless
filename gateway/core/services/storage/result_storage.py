"""
This module handle the access to the result store
"""

import os
import logging
from typing import Optional
from django.conf import settings

logger = logging.getLogger("gateway")


class ResultStorage:
    """Handles the storage and retrieval of user job results."""

    RESULT_FILE_EXTENSION = ".json"
    ENCODING = "utf-8"

    def __init__(self, username: str):
        """Initialize the storage path for a given user."""
        self.user_results_directory = os.path.join(settings.MEDIA_ROOT, username, "results")
        os.makedirs(self.user_results_directory, exist_ok=True)

    def __get_result_path(self, job_id: str) -> str:
        """Construct the full path for a result file."""
        return os.path.join(self.user_results_directory, f"{job_id}{self.RESULT_FILE_EXTENSION}")

    def get(self, job_id: str) -> Optional[str]:
        """
        Retrieve a result file for the given job ID.

        Args:
            job_id (str): the id for the job to get the result
        Returns:
                Optional[str]: content of the file
        """
        result_path = self.__get_result_path(job_id)
        if not os.path.exists(result_path):
            logger.info(
                "Result file for job ID '%s' not found in directory '%s'.",
                job_id,
                self.user_results_directory,
            )
            return None

        try:
            with open(result_path, "r", encoding="utf-8") as result_file:
                return result_file.read()
        except (UnicodeDecodeError, IOError) as e:
            logger.error(
                "Failed to read result file for job ID '%s': %s",
                job_id,
                str(e),
            )
            return None

    def save(self, job_id: str, result: str) -> None:
        """
        Save the result content to a file associated with the given job ID.

        Args:
            job_id (str): The unique identifier for the job. This will be used as the base
                        name for the result file.
            result (str): The job result content to be saved in the file.
        Returns:
            None
        """
        result_path = self.__get_result_path(job_id)

        with open(result_path, "w", encoding=self.ENCODING) as result_file:
            result_file.write(result)
            logger.info(
                "Result for job ID '%s' successfully saved at '%s'.",
                job_id,
                result_path,
            )
