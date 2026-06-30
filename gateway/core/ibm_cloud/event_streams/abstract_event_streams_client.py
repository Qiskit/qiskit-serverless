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

"""Abstract interface for job usage event publishing."""

from abc import ABC, abstractmethod


class EventStreamsClient(ABC):
    """Interface for job usage event publishing."""

    @abstractmethod
    def emit_job_started(self, job) -> None:
        """Publish or log a job_started event."""

    @abstractmethod
    def emit_job_in_progress(self, job) -> None:
        """Publish or log a job_in_progress event."""

    @abstractmethod
    def emit_job_ended(self, job) -> None:
        """Publish or log a job_ended event."""
