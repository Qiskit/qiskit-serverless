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
import json
import warnings
from dataclasses import dataclass
from typing import ClassVar, Literal, Optional, Dict, List, Any, Union

from qiskit_serverless.core.job import (
    Job,
    Configuration,
)
from qiskit_serverless.exception import QiskitServerlessException

GenericType = Literal["GENERIC"]
ApplicationType = Literal["APPLICATION"]
CircuitType = Literal["CIRCUIT"]


def _decode_arguments_schema(raw_schema: Any) -> Optional[Union[Dict[str, Any], bool]]:
    """Turn the text the gateway stores for ``arguments_schema`` back into a schema.

    The column holds text (defaulting to ``"{}"``), so a function without a schema arrives as
    an empty object rather than null, and both read back as ``None``. Sending ``{}`` is also how
    a schema is removed, which works because the upload only omits the field when it is ``None``
    rather than when it is falsy.

    A boolean is a valid JSON Schema and is kept as one: ``False`` rejects every instance, so
    reporting it as ``None`` would describe the strictest possible schema as no schema at all.
    Anything else is not a schema the gateway would have accepted, so it is reported rather than
    returned with a type the caller does not expect.

    Raises:
        QiskitServerlessException: if the stored value is not JSON, or is JSON but not an object
            or a boolean.
    """
    if isinstance(raw_schema, str):
        if not raw_schema:
            return None
        try:
            raw_schema = json.loads(raw_schema)
        except json.JSONDecodeError as error:
            raise QiskitServerlessException(f"The function arguments schema is not valid JSON: {error.msg}") from error

    if raw_schema is None or raw_schema == {}:
        return None
    if isinstance(raw_schema, (dict, bool)):
        return raw_schema
    raise QiskitServerlessException(
        "A function arguments schema must be an object or a boolean, "
        f"not {type(raw_schema).__name__}: {raw_schema!r}"
    )


def _decode_fields(data: Dict[str, Any], field_names: set) -> Dict[str, Any]:
    """Keep only known dataclass fields and decode the ones the gateway sends as text."""
    decoded = {k: v for k, v in data.items() if k in field_names}
    if "arguments_schema" in decoded:
        decoded["arguments_schema"] = _decode_arguments_schema(decoded["arguments_schema"])
    return decoded


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
        arguments_schema: JSON Schema describing valid arguments for this function. Normally an
            object; ``True`` and ``False`` are also valid schemas, accepting and rejecting every
            argument respectively. ``None`` means the function does not declare one, and setting
            it to ``{}`` on an upload removes the schema an earlier upload stored.

            The gateway applies the schema to the arguments *as this SDK encodes them*, not as
            they look in Python, so a ``QuantumCircuit`` argument is matched against
            ``{"__type__": "QuantumCircuit", "__value__": "<base64 QPY>"}`` and a numpy array
            against an object rather than an array. Describing either with
            ``{"type": "array"}`` therefore rejects every legitimate call. Constrain the plain
            arguments (counts, names, options, flags) and check only the ``__type__`` tag of the
            Qiskit ones. See ``specs/ARGUMENTS_VALIDATION.md``.
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
    runner: str = "ray"
    arguments_schema: Optional[Union[Dict[str, Any], bool]] = None
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
        return QiskitFunction(**_decode_fields(data, field_names))

    def __str__(self):
        if self.provider is not None:
            return f"QiskitFunction({self.provider}/{self.title})"
        return f"QiskitFunction({self.title})"

    def __repr__(self):
        return self.__str__()


class RunService(ABC):
    """Provide access to run a function and retrieve the jobs associated to that function"""

    @abstractmethod
    def jobs(self, function: QiskitFunction, **kwargs) -> List[Job]:
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
        provider: Optional[str] = None,
        *,
        compute_profile: Optional[str] = None,
    ) -> Job:
        """Run a function and return its job."""

    @abstractmethod
    def validate_arguments(
        self,
        title: str,
        arguments: Optional[Dict[str, Any]] = None,
        provider: Optional[str] = None,
    ) -> dict:
        """Validate arguments against a function's schema without creating a job."""


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

    def __init__(self, client: RunService, **kwargs):  # pylint:  disable=too-many-positional-arguments
        self._run_service = client
        super().__init__(**kwargs)

    @classmethod
    def from_json(cls, data: Dict[str, Any]):
        """Reconstructs QiskitPattern from dictionary."""
        field_names = set(f.name for f in dataclasses.fields(RunnableQiskitFunction))
        client = data["client"]
        return RunnableQiskitFunction(client, **_decode_fields(data, field_names))

    def run(self, **kwargs):
        """Run function

        Raises:
            QiskitServerlessException: validation exception

        Returns:
            Job: job handler for function execution
        """
        if self._run_service is None:
            raise ValueError("No clients specified for a function.")

        config = kwargs.pop("config", None)
        compute_profile = kwargs.pop("compute_profile", None)
        return self._run_service.run(
            program=self,
            arguments=kwargs,
            config=config,
            compute_profile=compute_profile,
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

    def jobs(self, **kwargs):
        """List of jobs created in this function.

        Raises:
            QiskitServerlessException: validation exception

        Returns:
            [Job] : list of jobs
        """

        if self._run_service is None:
            raise ValueError("No clients specified for a function.")

        jobs = self._run_service.jobs(function=self, **kwargs)
        return jobs

    def validate_arguments(self, arguments: dict) -> dict:
        """Validate arguments against the function's schema without creating a job.

        Args:
            arguments: arguments dict to validate against the function's schema

        Returns:
            dict: {"valid": True} if arguments are valid.

        Raises:
            QiskitServerlessException: if arguments are invalid or function not found.
        """
        if self._run_service is None:
            raise ValueError("No client specified for this function.")
        return self._run_service.validate_arguments(
            title=self.title,
            arguments=arguments,
            provider=self.provider,
        )


# pylint: disable=abstract-method
# pylint: disable=too-few-public-methods
class QiskitPattern(QiskitFunction):
    """
    [Deprecated since version 0.10.0] Use :class:`.QiskitFunction` instead.

    A provider for connecting to a ray head node. This class has been
    renamed to :class:`.QiskitFunction`.
    """
