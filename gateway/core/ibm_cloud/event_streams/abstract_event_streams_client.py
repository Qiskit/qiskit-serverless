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
    def emit_job_started(self, job, metric_type: str) -> None:
        """Publish or log a function_job_started event for the given metric."""

    @abstractmethod
    def emit_job_in_progress(self, job, metric_type: str) -> None:
        """Publish or log a function_job_in_progress event for the given metric."""

    @abstractmethod
    def emit_job_completed(self, job, metric_type: str) -> None:
        """Publish or log a function_job_completed event for the given metric."""
