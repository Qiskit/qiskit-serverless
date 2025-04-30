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
=================================================
Provider (:mod:`qiskit_serverless.core.function`)
=================================================

.. currentmodule:: qiskit_serverless.core.function

Qiskit Serverless function
==========================

.. autosummary::
    :toctree: ../stubs/

    QiskitFunction
"""
from abc import ABC, abstractmethod
import dataclasses
import warnings
from dataclasses import dataclass
from typing import ClassVar, Literal, Optional, Dict, List, Any, Tuple, Union

from qiskit_serverless.core.job import (
    Job,
    Configuration,
)

GenericType = Literal["GENERIC"]
ApplicationType = Literal["APPLICATION"]
CircuitType = Literal["CIRCUIT"]


@dataclass
class QiskitFunction:  # pylint: disable=too-many-instance-attributes
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

    title: str
    provider: Optional[str] = None
    entrypoint: Optional[str] = None
    working_dir: Optional[str] = "./"
    env_vars: Optional[Dict[str, str]] = None
    dependencies: Optional[List[str]] = None
    description: Optional[str] = None
    version: Optional[str] = None
    tags: Optional[List[str]] = None
    raw_data: Optional[Dict[str, Any]] = None
    image: Optional[str] = None
    validate: bool = True
    schema: Optional[str] = None
    type: Union[GenericType, ApplicationType, CircuitType] = GENERIC

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

    def _validate_function(self) -> Tuple[bool, List[str]]:
        """Validate function arguments using schema provided.

        Returns:
            Tuple[bool, List[str]]:
                boolean specifiying if function arguments are valid
                list of validation errors, if any
        """
        return True, []


class RunService(ABC):
    """Provide access to run a function and retrieve the jobs associated to that function"""

    @abstractmethod
    def jobs(self, **kwargs) -> List[Job]:
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
    ) -> Job:
        """Run a function and return its job."""


class RunnableQiskitFunction(QiskitFunction):
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

    _run_service: RunService = None

    def __init__(  # pylint:  disable=too-many-positional-arguments
        self, client: RunService, **kwargs
    ):
        self._run_service = client
        super().__init__(**kwargs)

    @classmethod
    def from_json(cls, data: Dict[str, Any]):
        """Reconstructs QiskitPattern from dictionary."""
        field_names = set(f.name for f in dataclasses.fields(RunnableQiskitFunction))
        client = data["client"]
        return RunnableQiskitFunction(
            client, **{k: v for k, v in data.items() if k in field_names}
        )

    def run(self, **kwargs):
        """Run function

        Raises:
            QiskitServerlessException: validation exception

        Returns:
            Job: job handler for function execution
        """
        if self._run_service is None:
            raise ValueError("No clients specified for a function.")

        if self.validate:
            is_valid, validation_errors = self._validate_function()
            if not is_valid:
                error_string = "\n".join(validation_errors)
                raise ValueError(
                    f"Function validation failed. Validation errors:\n {error_string}",
                )

        config = kwargs.pop("config", None)
        return self._run_service.run(
            program=self,
            arguments=kwargs,
            config=config,
        )

    def get_jobs(self):
        # pylint: disable=duplicate-code
        """List of jobs created in this function.

        Raises:
            QiskitServerlessException: validation exception

        Returns:
            [Job] : list of jobs
        """
        warnings.warn(
            "`get_jobs` method has been deprecated. "
            "And will be removed in future releases. "
            "Please, use `jobs` instead.",
            DeprecationWarning,
        )
        return self.jobs()

    def jobs(self):
        """List of jobs created in this function.

        Raises:
            QiskitServerlessException: validation exception

        Returns:
            [Job] : list of jobs
        """

        if self._run_service is None:
            raise ValueError("No clients specified for a function.")

        if self.validate:
            is_valid, validation_errors = self._validate_function()
            if not is_valid:
                error_string = "\n".join(validation_errors)
                raise ValueError(
                    f"Function validation failed. Validation errors:\n {error_string}",
                )

        jobs = self._run_service.jobs(
            title=self.title,
            provider=self.provider,
        )
        return jobs


# pylint: disable=abstract-method
# pylint: disable=too-few-public-methods
class QiskitPattern(QiskitFunction):
    """
    [Deprecated since version 0.10.0] Use :class:`.QiskitFunction` instead.

    A provider for connecting to a ray head node. This class has been
    renamed to :class:`.QiskitFunction`.
    """
