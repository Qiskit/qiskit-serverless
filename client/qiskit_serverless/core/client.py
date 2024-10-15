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
================================================
Provider (:mod:`qiskit_serverless.core.client`)
================================================

.. currentmodule:: qiskit_serverless.core.client

Qiskit Serverless provider
===========================

.. autosummary::
    :toctree: ../stubs/

    ComputeResource
    BaseClient
"""
import warnings
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, Union

from qiskit_ibm_runtime import QiskitRuntimeService

from qiskit_serverless.core.job import (
    Job,
    Configuration,
)
from qiskit_serverless.core.function import QiskitFunction
from qiskit_serverless.utils import JsonSerializable
from qiskit_serverless.visualizaiton import Widget


class BaseClient(JsonSerializable, ABC):
    """
    A client class for specifying custom compute resources.

    Example:
        >>> client = BaseClient(
        >>>    name="<NAME>",
        >>>    host="<HOST>",
        >>>    token="<TOKEN>",
        >>>    compute_resource=ComputeResource(
        >>>        name="<COMPUTE_RESOURCE_NAME>",
        >>>        host="<COMPUTE_RESOURCE_HOST>"
        >>>    ),
        >>> )
    """

    def __init__(  # pylint:  disable=too-many-positional-arguments
        self, name: str, host: Optional[str] = None, token: Optional[str] = None
    ):
        """
        Initialize a BaseClient instance.

        Args:
            name: name of client
            host: host of client a.k.a managers host
            token: authentication token for manager
        """
        self.name = name
        self.host = host
        self.token = token

    @classmethod
    @abstractmethod
    def from_dict(cls, dictionary: dict):
        """Converts dict to object."""

    def __eq__(self, other):
        if isinstance(other, BaseClient):
            return self.name == other.name

        return False

    def __repr__(self):
        return f"<{self.name}>"

    ####################
    ####### JOBS #######
    ####################
    @abstractmethod
    def get_jobs(self, **kwargs) -> List[Job]:
        """Return list of jobs.

        Returns:
            list of jobs.
        """

    @abstractmethod
    def get_job(self, job_id: str) -> Optional[Job]:
        """Returns job by job id.

        Args:
            job_id: job id

        Returns:
            Job instance
        """

    def get_job_by_id(self, job_id: str) -> Optional[Job]:
        """Returns job by job id.

        Args:
            job_id: job id

        Returns:
            Job instance
        """
        warnings.warn(
            "`get_job_by_id` method has been deprecated. "
            "And will be removed in future releases. "
            "Please, use `get_job` instead.",
            DeprecationWarning,
        )
        return self.get_job(job_id)

    @abstractmethod
    def run(
        self,
        program: Union[QiskitFunction, str],
        arguments: Optional[Dict[str, Any]] = None,
        config: Optional[Configuration] = None,
    ) -> Job:
        """Execute a program as a async job.

        Example:
            >>> serverless = QiskitServerless()
            >>> program = QiskitFunction(
            >>>     "job.py",
            >>>     arguments={"arg1": "val1"},
            >>>     dependencies=["requests"]
            >>> )
            >>> job = serverless.run(program)
            >>> # <Job | ...>

        Args:
            arguments: arguments to run program with
            program: Program object

        Returns:
            Job
        """

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
        """Return filtered logs."""

    #########################
    ####### Functions #######
    #########################

    @abstractmethod
    def upload(self, program: QiskitFunction) -> Optional[QiskitFunction]:
        """Uploads program."""

    @abstractmethod
    def get_functions(self, **kwargs) -> List[QiskitFunction]:
        """Returns list of available programs."""

    @abstractmethod
    def get_function(
        self, title: str, provider: Optional[str] = None
    ) -> Optional[QiskitFunction]:
        """Returns program based on parameters."""

    def get(
        self, title: str, provider: Optional[str] = None
    ) -> Optional[QiskitFunction]:
        """Returns program based on parameters."""
        warnings.warn(
            "`get` method has been deprecated. "
            "And will be removed in future releases. "
            "Please, use `get_function` instead.",
            DeprecationWarning,
        )
        return self.get_function(title, provider=provider)

    def list(self, **kwargs) -> List[QiskitFunction]:
        """Returns list of available programs."""
        warnings.warn(
            "`list` method has been deprecated. "
            "And will be removed in future releases. "
            "Please, use `get_functions` instead.",
            DeprecationWarning,
        )
        return self.get_functions(**kwargs)

    ######################
    ####### Widget #######
    ######################

    def widget(self):
        """Widget for information about provider and jobs."""
        return Widget(self).show()
