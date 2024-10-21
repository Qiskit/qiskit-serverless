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
    OT_PROGRAM_NAME,
    ENV_JOB_ARGUMENTS,
)
from qiskit_serverless.core.client import BaseClient
from qiskit_serverless.core.job import (
    Job,
    Configuration,
)
from qiskit_serverless.core.function import QiskitFunction, RunnableQiskitFunction
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
        self._patterns = []

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
        title = ""
        if isinstance(program, QiskitFunction):
            title = program.title
        else:
            title = str(program)

        for pattern in self._patterns:
            if pattern["title"] == title:
                saved_program = pattern
        if saved_program[  # pylint: disable=possibly-used-before-assignment
            "dependencies"
        ]:
            dept = json.loads(saved_program["dependencies"])
            for dependency in dept:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", dependency]
                )
        arguments = arguments or {}
        env_vars = {
            **(saved_program["env_vars"] or {}),
            **{OT_PROGRAM_NAME: saved_program["title"]},
            **{"PATH": os.environ["PATH"]},
            **{ENV_JOB_ARGUMENTS: json.dumps(arguments, cls=QiskitObjectsEncoder)},
        }

        with Popen(
            ["python", saved_program["working_dir"] + saved_program["entrypoint"]],
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

        job = Job(job_id=str(uuid4()), client=self)
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

    def upload(self, program: QiskitFunction) -> Optional[QiskitFunction]:
        # check if entrypoint exists
        if not os.path.exists(os.path.join(program.working_dir, program.entrypoint)):
            raise QiskitServerlessException(
                f"Entrypoint file [{program.entrypoint}] does not exist "
                f"in [{program.working_dir}] working directory."
            )

        pattern = {
            "title": program.title,
            "provider": program.provider,
            "entrypoint": program.entrypoint,
            "working_dir": program.working_dir,
            "env_vars": program.env_vars,
            "arguments": json.dumps({}),
            "dependencies": json.dumps(program.dependencies or []),
            "client": self,
        }
        self._patterns.append(pattern)
        return QiskitFunction.from_json(pattern)

    def functions(self, **kwargs) -> List[RunnableQiskitFunction]:
        """Returns list of programs."""
        return [QiskitFunction.from_json(program) for program in self._patterns]

    def function(
        self, title: str, provider: Optional[str] = None
    ) -> Optional[RunnableQiskitFunction]:
        functions = {function.title: function for function in self.functions()}
        return functions.get(title)
