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

Qiskit Serverless Runnable Function With Steps
==============================================

.. autosummary::
    :toctree: ../stubs/

    RunnableQiskitFunctionWithSteps
"""

import dataclasses
from typing import Dict, Any, cast

from qiskit_serverless.core.jobs import Workflow
from .run_service import QiskitFunction, RunService

# pylint: disable=duplicate-code
class RunnableQiskitFunctionWithSteps(QiskitFunction):
    """Serverless QiskitFunctionWithSteps.

    Args:
        title: program name
        provider: Qiskit Function provider reference
        entrypoint: is a script that will be executed as a job
            ex: job.py
        env_vars: env vars
        dependencies: list of python dependencies to execute a program
        working_dir: directory where entrypoint file is located (max size 50MB)
        description: description of a program
        version: version of a program
    """

    _run_service: RunService = None

    def __init__(self, client: RunService, **kwargs):
        self._run_service = client
        super().__init__(**kwargs)

    @classmethod
    def from_json(cls, data: Dict[str, Any]):
        """Reconstructs QiskitPattern from dictionary."""
        field_names = set(
            f.name for f in dataclasses.fields(RunnableQiskitFunctionWithSteps)
        )
        client = data["client"]
        return RunnableQiskitFunctionWithSteps(
            client, **{k: v for k, v in data.items() if k in field_names}
        )

    def run(self, **kwargs):
        """Run function

        Raises:
            QiskitServerlessException: validation exception

        Returns:
            Workflow: workflow handler for function with steps execution
        """
        if self._run_service is None:
            raise ValueError("No clients specified for a function.")

        config = kwargs.pop("config", None)
        return cast(
            Workflow,
            self._run_service.run(
                program=self,
                arguments=kwargs,
                config=config,
            ),
        )

    def jobs(self):
        """List of jobs created in this function.

        Raises:
            QiskitServerlessException: validation exception

        Returns:
            [Job] : list of jobs
        """

        if self._run_service is None:
            raise ValueError("No clients specified for a function.")

        jobs = self._run_service.jobs(
            title=self.title,
            provider=self.provider,
        )
        return jobs
