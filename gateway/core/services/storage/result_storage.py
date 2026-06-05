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

"""Abstract base class for result storage."""

from abc import ABC, abstractmethod


class ResultStorage(ABC):
    """Abstract interface for job result storage.

    Subclasses implement backend-specific logic for reading and writing
    job results (e.g. local filesystem for Ray, COS for Fleets).
    """

    @abstractmethod
    def get(self) -> str | None:
        """Retrieve the result for the job.

        Returns:
            The result string, or None if the result is not available.
        """

    @abstractmethod
    def save(self, result: str) -> None:
        """Persist the result for the job.

        Args:
            result: The result string to store.
        """
