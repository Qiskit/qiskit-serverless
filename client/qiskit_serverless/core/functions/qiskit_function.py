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

Qiskit Serverless Function
==========================

.. autosummary::
    :toctree: ../stubs/

    QiskitFunction
"""

import dataclasses
from dataclasses import dataclass
from typing import ClassVar, Literal, Optional, Dict, List, Any, Union

GenericType = Literal["GENERIC"]
ApplicationType = Literal["APPLICATION"]
CircuitType = Literal["CIRCUIT"]


@dataclass
class QiskitFunctionStep:  # pylint: disable=too-many-instance-attributes
    """Serverless QiskitFunctionStep.

    Args:
        id: database identifier
        base_function: id of the stepped function
        function: function to execute
        depends_on: the step that should finish before this starts
    """

    id: str
    base_function: str
    function: str
    depends_on: str


@dataclass
class QiskitFunction:  # pylint: disable=too-many-instance-attributes
    """Serverless QiskitFunction.

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
    title: str
    provider: Optional[str] = None
    description: Optional[str] = None
    version: Optional[str] = None
    tags: Optional[List[str]] = None
    type: Union[GenericType, ApplicationType, CircuitType] = GENERIC

    # function specific data
    entrypoint: Optional[str] = None
    working_dir: Optional[str] = "./"
    env_vars: Optional[Dict[str, str]] = None
    dependencies: Optional[List[str]] = None
    image: Optional[str] = None

    # steps specific data
    steps: List[QiskitFunctionStep] = None

    def __post_init__(self):
        title_has_provider = "/" in self.title
        if title_has_provider:
            title_split = self.title.split("/")
            if len(title_split) > 2:
                raise ValueError("Invalid title: it can only contain one slash.")
            if self.provider != title_split[0] and self.provider is not None:
                raise ValueError(
                    "Invalid provider: you provided two different "
                    + f"providers [{self.provider}] and [{title_split[0]}]."
                )
            self.provider = title_split[0]
            self.title = title_split[1]

        if (self.image or self.entrypoint) and self.steps and len(self.steps):
            raise ValueError("Cannot contain steps and a function at the same time.")

    @classmethod
    def from_json(cls, data: Dict[str, Any]):
        """Reconstructs QiskitPattern from dictionary."""
        field_names = set(f.name for f in dataclasses.fields(QiskitFunction))
        return QiskitFunction(**{k: v for k, v in data.items() if k in field_names})

    def __str__(self):
        if self.provider is not None:
            return f"QiskitFunction({self.provider}/{self.title})"
        return f"QiskitFunction({self.title})"

    def __repr__(self):
        return self.__str__()
