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

    LocalClient
"""
# pylint: disable=duplicate-code
import json
import os.path
import os
import re
import sys
from typing import Optional, List, Dict, Any, Union
from uuid import uuid4

import subprocess
from subprocess import Popen

from qiskit_ibm_runtime import QiskitRuntimeService

from qiskit_serverless.core.constants import (
    ENV_JOB_ID_GATEWAY,
    OT_PROGRAM_NAME,
)
from qiskit_serverless.core.client import BaseClient
from qiskit_serverless.core.job import (
    Job,
    Configuration,
)
from qiskit_serverless.core.function import QiskitFunction, RunnableQiskitFunction
from qiskit_serverless.core.local_functions_store import LocalFunctionsStore
from qiskit_serverless.exception import QiskitServerlessException
from qiskit_serverless.serializers.program_serializers import (
    QiskitObjectsEncoder,
)


class LocalClient(BaseClient):
    """LocalClient."""

    def __init__(self):
        """Local client

        Args:

        Example:
            >>> local = LocalClient()
        """
        super().__init__("local-client")
        self.in_test = os.getenv("IN_TEST")
        self._jobs = {}
        self._functions = LocalFunctionsStore(self)

    @classmethod
    def from_dict(cls, dictionary: dict):
        return LocalClient(**dictionary)

    ####################
    ####### JOBS #######
    ####################

    def job(self, job_id: str) -> Optional[Job]:
        return self._jobs[job_id]["job"]

    def jobs(self, **kwargs) -> List[Job]:
        return [job["job"] for job in list(self._jobs.values())]

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

        if saved_program.dependencies:
            for dependency in saved_program.dependencies:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", dependency]
                )
        arguments = arguments or {}
        env_vars = {
            **(saved_program.env_vars or {}),
            **{OT_PROGRAM_NAME: saved_program.title},
            **{"PATH": os.environ["PATH"]},
        }

        job_id_gateway = os.environ.get(ENV_JOB_ID_GATEWAY)
        data_path = os.environ.get("DATA_PATH", "/data")

        if not os.path.exists(data_path):
            raise QiskitServerlessException(
                f"Data path '{data_path}' does not exist. "
                f"Please ensure the DATA_PATH directory is created."
            )

        arguments_dir = os.path.join(data_path, "arguments")
        if not os.path.exists(arguments_dir):
            os.makedirs(arguments_dir)

        arguments_file_path = os.path.join(arguments_dir, f"{job_id_gateway}.json")
        with open(arguments_file_path, "w", encoding="utf-8") as f:
            json.dump(arguments, f, cls=QiskitObjectsEncoder)

        with Popen(
            [
                "python",
                os.path.join(saved_program.working_dir, saved_program.entrypoint),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            env=env_vars,
        ) as pipe:
            status = "SUCCEEDED"
            if pipe.wait():
                status = "FAILED"
            output, _ = pipe.communicate()

        results = re.search("\nSaved Result:(.+?):End Saved Result\n", output)
        result = ""
        if results:
            result = results.group(1)

        job = Job(job_id=str(uuid4()), job_service=self)
        self._jobs[job.job_id] = {
            "status": status,
            "logs": output,
            "result": result,
            "job": job,
        }
        return job

    def status(self, job_id: str):
        return self._jobs[job_id]["status"]

    def stop(self, job_id: str, service: Optional[QiskitRuntimeService] = None):
        """Stops job/program."""
        return f"job:{job_id} has already stopped"

    def result(self, job_id: str):
        return self._jobs[job_id]["result"]

    def logs(self, job_id: str):
        return self._jobs[job_id]["logs"]

    def filtered_logs(self, job_id: str, **kwargs):
        """Return filtered logs."""
        raise NotImplementedError

    #########################
    ####### Functions #######
    #########################

    def upload(self, program: QiskitFunction) -> Optional[RunnableQiskitFunction]:
        # check if entrypoint exists
        return self._functions.upload(program)

    def functions(self, **kwargs) -> List[RunnableQiskitFunction]:
        return self._functions.functions()

    def function(
        self, title: str, provider: Optional[str] = None
    ) -> Optional[RunnableQiskitFunction]:
        return self._functions.function(title)
