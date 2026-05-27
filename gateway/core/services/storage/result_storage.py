"""
This module handle the access to the result store
"""

import json
import os
import logging
from typing import Optional
from django.conf import settings

from core.constants import RESULTS_PATH
from qiskit_serverless.exception import QiskitServerlessException

logger = logging.getLogger("core.ResultStorage")


"""Abstract base class for arguments storage."""

from abc import ABC, abstractmethod
from typing import Optional


class BaseResultStorage(ABC):
    """Abstract interface for job arguments storage."""

    @abstractmethod
    def get(self) -> Optional[str]:
        """Retrieve arguments for the job."""

    @abstractmethod
    def save(self, arguments: str) -> None:
        """Persist arguments for the job."""


class ResultStorage(BaseResultStorage):
    """Handles the storage and retrieval of user job results."""

    RESULT_FILE_EXTENSION = ".json"
    ENCODING = "utf-8"

    def __init__(self, username: str):
        """Initialize the storage path for a given user."""
        self.user_results_directory = os.path.join(settings.MEDIA_ROOT, username, "results")
        os.makedirs(self.user_results_directory, exist_ok=True)

    def __get_result_path(self) -> str:
        """Check if the file path specified by the ``RESULTS_PATH`` environment variable,
        which is set by the runner (Ray or Fleets) at job submission, exists and legal."""
        results_path = os.environ.get(RESULTS_PATH)
        if not results_path:
            raise QiskitServerlessException(
                "Error getting arguments: RESULTS_PATH environment variable is missing or empty"
            )

        os.makedirs(os.path.dirname(results_path), exist_ok=True)

        if not os.path.isfile(results_path):
            raise QiskitServerlessException(f"Error saving results: {results_path} is not a file or doesn't exist")

        return results_path

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
                "[get] job_id=%s | Result file not found %s",
                job_id,
                result_path,
            )
            return None

        try:
            with open(result_path, "r", encoding="utf-8") as result_file:
                content = result_file.read()
                logger.info(
                    "[get] job_id=%s | Result file read %s",
                    job_id,
                    result_path,
                )
                return content
        except (UnicodeDecodeError, IOError) as e:
            logger.error(
                "[get] job_id=%s | Failed to read result file: %s",
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
        result_path = self.__get_result_path()

        with open(result_path, "w", encoding=self.ENCODING) as result_file:
            result_file.write(result)

        logger.info(
            "[save] job_id=%s | Result saved ok %s",
            job_id,
            result_path,
        )
