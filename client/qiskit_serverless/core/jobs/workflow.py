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

Qiskit Serverless Workflow
==========================

.. autosummary::
    :toctree: ../stubs/

    Workflow
    WorkflowStep
"""

from dataclasses import dataclass
import dataclasses
from typing import Any, ClassVar, Dict, Literal, List

from qiskit_serverless.core.jobs import WorkflowService, Job

GenericType = Literal["GENERIC"]
ApplicationType = Literal["APPLICATION"]
CircuitType = Literal["CIRCUIT"]


@dataclass
class Workflow:  # pylint: disable=too-many-instance-attributes
    """Serverless QiskitPattern.

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

    GENERIC: ClassVar[GenericType] = "GENERIC"
    APPLICATION: ClassVar[ApplicationType] = "APPLICATION"
    CIRCUIT: ClassVar[CircuitType] = "CIRCUIT"

    # common data
    id: str
    service: WorkflowService
    jobs: List[Job]
    function: str  # The base function
    user: str  # The user that executed the flow

    @classmethod
    def from_json(cls, data: Dict[str, Any]):
        """Reconstructs QiskitPattern from dictionary."""
        field_names = set(f.name for f in dataclasses.fields(Workflow))
        return Workflow(**{k: v for k, v in data.items() if k in field_names})
