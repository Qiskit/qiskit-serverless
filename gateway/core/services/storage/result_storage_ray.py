# This code is part of a Qiskit project.
#
# (C) IBM 2026
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Ray implementation of result storage."""

import logging
import os

from django.conf import settings

from core.models import Job
from core.services.storage.result_storage import ResultStorage

logger = logging.getLogger("core.RayResultStorage")


class RayResultStorage(ResultStorage):
    """Handles the storage and retrieval of user job results for Ray jobs."""

    RESULT_FILE_EXTENSION = ".json"
    ENCODING = "utf-8"

    def __init__(self, job: Job) -> None:
        """Initialize the storage with the user's results directory.

        Args:
            job: The Job instance to store/retrieve results for.
        """
        self._job_id = str(job.id)
        self.user_results_directory = os.path.join(settings.MEDIA_ROOT, job.author.username, "results")
        os.makedirs(self.user_results_directory, exist_ok=True)

    def _get_result_path(self) -> str:
        """Construct the full filesystem path for this job's result file.

        Returns:
            The absolute path to the result JSON file.
        """
        return os.path.join(self.user_results_directory, f"{self._job_id}{self.RESULT_FILE_EXTENSION}")

    def get(self) -> str | None:
        """Retrieve the result for this job from the local filesystem.

        Returns:
            The result string, or None if the file does not exist or cannot be read.
        """
        result_path = self._get_result_path()
        if not os.path.exists(result_path):
            logger.info(
                "[get] job_id=%s | Result file not found %s",
                self._job_id,
                result_path,
            )
            return None

        try:
            with open(result_path, "r", encoding=self.ENCODING) as result_file:
                content = result_file.read()
                logger.info(
                    "[get] job_id=%s | Result file read %s",
                    self._job_id,
                    result_path,
                )
                return content
        except (UnicodeDecodeError, IOError) as e:
            logger.error(
                "[get] job_id=%s | Failed to read result file: %s",
                self._job_id,
                str(e),
            )
            return None

    def save(self, result: str) -> None:
        """Persist the result for this job to the local filesystem.

        Args:
            result: The result string to write to the file.
        """
        result_path = self._get_result_path()

        with open(result_path, "w", encoding=self.ENCODING) as result_file:
            result_file.write(result)

        logger.info(
            "[save] job_id=%s | Result saved ok %s",
            self._job_id,
            result_path,
        )
