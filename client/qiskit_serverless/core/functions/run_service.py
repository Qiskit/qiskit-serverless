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
Provider (:mod:`qiskit_serverless.core.functions`)
=============================================

.. currentmodule:: qiskit_serverless.core.functions

Qiskit Serverless Run Service
=============================

.. autosummary::
    :toctree: ../stubs/

    RunService
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, List, Any, Union

from qiskit_serverless.core.jobs import Job, Configuration, Workflow
from .qiskit_function import QiskitFunction


class RunService(ABC):
    """Provide access to run a function and retrieve the jobs associated to that function"""

    @abstractmethod
    def jobs(self, **kwargs) -> List[Union[Job, Workflow]]:
        """Return list of jobs.

        Returns:
            list of jobs.
        """

    @abstractmethod
    def run(
        self,
        program: Union[QiskitFunction, str],
        arguments: Optional[Dict[str, Any]] = None,
        config: Optional[Configuration] = None,
    ) -> Union[Job, Workflow]:
        """Run a function and return its job."""
