# This code is a Qiskit project.
#
# (C) Copyright IBM 2022.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.


"""
=============================================
Provider (:mod:`qiskit_serverless.core.jobs`)
=============================================

.. currentmodule:: qiskit_serverless.core.jobs

Qiskit Serverless JobService
============================

.. autosummary::
    :toctree: ../stubs/

    JobService
"""

# pylint: disable=duplicate-code
from abc import ABC, abstractmethod
from typing import Any, Optional, Union

import ray.runtime_env

from qiskit_ibm_runtime import QiskitRuntimeService

RuntimeEnv = ray.runtime_env.RuntimeEnv


class JobService(ABC):
    """Provide access to job information"""

    @abstractmethod
    def status(self, job_id: str) -> str:
        """Check status."""

    @abstractmethod
    def stop(
        self, job_id: str, service: Optional[QiskitRuntimeService] = None
    ) -> Union[str, bool]:
        """Stops job/program."""

    @abstractmethod
    def result(self, job_id: str) -> Any:
        """Return results."""

    @abstractmethod
    def logs(self, job_id: str) -> str:
        """Return logs."""

    @abstractmethod
    def filtered_logs(self, job_id: str, **kwargs) -> str:
        """Returns logs of the job.
        Args:
            job_id: The job's logs
            include: rex expression finds match in the log line to be included
            exclude: rex expression finds match in the log line to be excluded
        """
