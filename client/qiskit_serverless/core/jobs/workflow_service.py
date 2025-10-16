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

Qiskit Serverless Workflow Service
==================================

.. autosummary::
    :toctree: ../stubs/

    WorkflowService
"""

# pylint: disable=duplicate-code
from abc import ABC, abstractmethod
from typing import Any, Optional, Union

import ray.runtime_env

from qiskit_ibm_runtime import QiskitRuntimeService

RuntimeEnv = ray.runtime_env.RuntimeEnv


class WorkflowService(ABC):
    """Provide access to job information"""

    @abstractmethod
    def workflow_status(self, workflow_id: str) -> str:
        """Check status."""

    @abstractmethod
    def workflow_stop(
        self, workflow_id: str, service: Optional[QiskitRuntimeService] = None
    ) -> Union[str, bool]:
        """Stops all the jobs."""

    @abstractmethod
    def workflow_result(self, workflow_id: str) -> Any:
        """Return results."""

    @abstractmethod
    def workflow_logs(self, workflow_id: str) -> str:
        """Return logs."""

    @abstractmethod
    def workflow_filtered_logs(self, workflow_id: str, **kwargs) -> str:
        """Returns logs filtered"""
