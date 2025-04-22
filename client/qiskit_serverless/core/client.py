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
from typing import Optional, List

from qiskit_serverless.core.job import Job, JobService
from qiskit_serverless.core.function import (
    QiskitFunction,
    RunnableQiskitFunction,
    RunService,
)
from qiskit_serverless.utils import JsonSerializable


class BaseClient(JobService, RunService, JsonSerializable, ABC):
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
        self,
        name: str,
        host: Optional[str] = None,
        token: Optional[str] = None,
        instance: Optional[str] = None,
    ):
        """
        Initialize a BaseClient instance.

        Args:
            name: name of client
            host: host of client a.k.a managers host
            token: authentication token for manager
            instance: IBM Cloud CRN
        """
        self.name = name
        self.host = host
        self.token = token
        self.instance = instance

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
    def jobs(self, **kwargs) -> List[Job]:
        """Return list of jobs.

        Returns:
            list of jobs.
        """

    @abstractmethod
    def job(self, job_id: str) -> Optional[Job]:
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
        return self.job(job_id)

    def get_jobs(self, **kwargs) -> List[Job]:
        # pylint: disable=duplicate-code
        """Return list of jobs.

        Returns:
            list of jobs.
        """
        warnings.warn(
            "`get_jobs` method has been deprecated. "
            "And will be removed in future releases. "
            "Please, use `jobs` instead.",
            DeprecationWarning,
        )
        return self.jobs(**kwargs)

    #########################
    ####### Functions #######
    #########################

    @abstractmethod
    def upload(self, program: QiskitFunction) -> Optional[RunnableQiskitFunction]:
        """Uploads program."""

    @abstractmethod
    def functions(self, **kwargs) -> List[RunnableQiskitFunction]:
        """Returns list of available programs."""

    @abstractmethod
    def function(
        self, title: str, provider: Optional[str] = None
    ) -> Optional[RunnableQiskitFunction]:
        """Returns program based on parameters."""

    def get(
        self, title: str, provider: Optional[str] = None
    ) -> Optional[RunnableQiskitFunction]:
        """Returns program based on parameters."""
        warnings.warn(
            "`get` method has been deprecated. "
            "And will be removed in future releases. "
            "Please, use `get_function` instead.",
            DeprecationWarning,
        )
        return self.function(title, provider=provider)

    def list(self, **kwargs) -> List[RunnableQiskitFunction]:
        """Returns list of available programs."""
        warnings.warn(
            "`list` method has been deprecated. "
            "And will be removed in future releases. "
            "Please, use `get_functions` instead.",
            DeprecationWarning,
        )
        return self.functions(**kwargs)

    ######################
    ####### Widget #######
    ######################

    def widget(self):
        """Widget for information about provider and jobs."""
        # prevent ciclic import
        from qiskit_serverless.visualization import (  # pylint: disable=import-outside-toplevel
            Widget,
        )

        return Widget(self).show()
