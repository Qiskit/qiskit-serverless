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
import dataclasses
from dataclasses import dataclass
from typing import Optional, Dict, List, Any, Tuple


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
    job_client: Optional[Any] = None
    image: Optional[str] = None
    validate: bool = True
    schema: Optional[str] = None

    def __post_init__(self):
        title_has_provider = "/" in self.title
        if title_has_provider:
            title_split = self.title.split("/")
            if len(title_split) > 2:
                raise ValueError("Invalid title: it can only contain one slash.")
            if self.provider != title_split[0]:
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

    def run(self, **kwargs):
        """Run function

        Raises:
            QiskitServerlessException: validation exception

        Returns:
            Job: job handler for function execution
        """
        if self.job_client is None:
            raise ValueError("No clients specified for a function.")

        if self.validate:
            is_valid, validation_errors = self._validate_function()
            if not is_valid:
                error_string = "\n".join(validation_errors)
                raise ValueError(
                    f"Function validation failed. Validation errors:\n {error_string}",
                )

        config = kwargs.pop("config", None)
        return self.job_client.run(
            program=self.title,
            provider=self.provider,
            arguments=kwargs,
            config=config,
        )

    def _validate_function(self) -> Tuple[bool, List[str]]:
        """Validate function arguments using schema provided.

        Returns:
            Tuple[bool, List[str]]:
                boolean specifiying if function arguments are valid
                list of validation errors, if any
        """
        return True, []


# pylint: disable=abstract-method
class QiskitPattern(QiskitFunction):
    """
    [Deprecated since version 0.10.0] Use :class:`.QiskitFunction` instead.

    A provider for connecting to a ray head node. This class has been
    renamed to :class:`.QiskitFunction`.
    """
