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

    RayClient
"""
# pylint: disable=duplicate-code
import json
from typing import Optional, List, Dict, Any, Union
from uuid import uuid4

from ray.dashboard.modules.job.sdk import JobSubmissionClient
from qiskit_ibm_runtime import QiskitRuntimeService

from qiskit_serverless.core.constants import (
    OT_PROGRAM_NAME,
    ENV_JOB_ARGUMENTS,
)
from qiskit_serverless.core.job import (
    Configuration,
    Job,
)
from qiskit_serverless.core.function import QiskitFunction, RunnableQiskitFunction
from qiskit_serverless.core.local_functions_store import LocalFunctionsStore
from qiskit_serverless.exception import QiskitServerlessException
from qiskit_serverless.serializers.program_serializers import (
    QiskitObjectsEncoder,
)

from qiskit_serverless.core.client import BaseClient


class RayClient(BaseClient):
    """RayClient."""

    def __init__(self, host: str):
        """Ray client

        Args:
            host: ray head node host

        Example:
            >>> ray_provider = RayClient("http://localhost:8265")
        """
        super().__init__("ray-client", host)
        self.job_submission_client = JobSubmissionClient(host)
        self._functions = LocalFunctionsStore(self)

    @classmethod
    def from_dict(cls, dictionary: dict):
        return RayClient(**dictionary)

    ####################
    ####### JOBS #######
    ####################

    def jobs(self, **kwargs) -> List[Job]:
        """Return list of jobs.

        Returns:
            list of jobs.
        """
        return [
            Job(job.job_id, job_service=self)
            for job in self.job_submission_client.list_jobs()
        ]

    def job(self, job_id: str) -> Optional[Job]:
        """Returns job by job id.

        Args:
            job_id: job id

        Returns:
            Job instance
        """
        return Job(
            self.job_submission_client.get_job_info(job_id).submission_id,
            job_service=self,
        )

    def run(
        self,
        program: Union[QiskitFunction, str],
        arguments: Optional[Dict[str, Any]] = None,
        config: Optional[Configuration] = None,
    ) -> Job:
        # pylint: disable=too-many-locals
        title = program.title if isinstance(program, QiskitFunction) else str(program)

        saved_program = self.function(title)

        if not saved_program:
            raise QiskitServerlessException(
                "QiskitFunction provided is not uploaded to the client. Use upload() first."
            )

        arguments = arguments or {}
        entrypoint = f"python {saved_program.entrypoint}"

        # set program name so OT can use it as parent span name
        env_vars = {
            **(saved_program.env_vars or {}),
            **{OT_PROGRAM_NAME: saved_program.title},
            **{ENV_JOB_ARGUMENTS: json.dumps(arguments, cls=QiskitObjectsEncoder)},
        }

        job_id = self.job_submission_client.submit_job(
            entrypoint=entrypoint,
            submission_id=f"qs_{uuid4()}",
            runtime_env={
                "working_dir": saved_program.working_dir,
                "pip": saved_program.dependencies,
                "env_vars": env_vars,
            },
        )
        return Job(job_id=job_id, job_service=self)

    def status(self, job_id: str) -> str:
        """Check status."""
        return self.job_submission_client.get_job_status(job_id).value

    def stop(
        self, job_id: str, service: Optional[QiskitRuntimeService] = None
    ) -> Union[str, bool]:
        """Stops job/program."""
        return self.job_submission_client.stop_job(job_id)

    def result(self, job_id: str) -> Any:
        """Return results."""
        return self.logs(job_id)

    def logs(self, job_id: str) -> str:
        """Return logs."""
        return self.job_submission_client.get_job_logs(job_id)

    def filtered_logs(self, job_id: str, **kwargs) -> str:
        """Return filtered logs."""
        raise NotImplementedError

    #########################
    ####### Functions #######
    #########################

    def upload(self, program: QiskitFunction) -> Optional[RunnableQiskitFunction]:
        """Uploads program."""
        return self._functions.upload(program)

    def functions(self, **kwargs) -> List[RunnableQiskitFunction]:
        """Returns list of available programs."""
        return self._functions.functions()

    def function(
        self, title: str, provider: Optional[str] = None
    ) -> Optional[RunnableQiskitFunction]:
        """Returns program based on parameters."""
        return self._functions.function(title)
