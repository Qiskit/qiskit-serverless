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
Provider (:mod:`quantum_serverless.core.job`)
=============================================

.. currentmodule:: quantum_serverless.core.job

Quantum serverless job
======================

.. autosummary::
    :toctree: ../stubs/

    RuntimeEnv
    Job
"""
import json
import logging
from typing import Iterator
from uuid import uuid4

import ray.runtime_env
import requests
from ray.dashboard.modules.job.sdk import JobSubmissionClient

from quantum_serverless.core.program import Program
from quantum_serverless.core.constants import OT_PROGRAM_NAME

RuntimeEnv = ray.runtime_env.RuntimeEnv


class BaseJobClient:
    def run_program(self, program: Program) -> 'Job':
        raise NotImplementedError

    def status(self, job_id: str):
        raise NotImplementedError

    def stop(self, job_id: str):
        raise NotImplementedError

    def logs(self, job_id: str):
        raise NotImplementedError

    def result(self, job_id: str):
        raise NotImplementedError


class RayJobClient(BaseJobClient):
    def __init__(self, client: JobSubmissionClient):
        self._job_client = client

    def status(self, job_id: str):
        return self._job_client.get_job_status(job_id)

    def stop(self, job_id: str):
        return self._job_client.stop_job(job_id)

    def logs(self, job_id: str):
        return self._job_client.get_job_logs(job_id)

    def result(self, job_id: str):
        return self.logs(job_id)

    def run_program(self, program: Program):
        arguments = ""
        if program.arguments is not None:
            arg_list = []
            for key, value in program.arguments.items():
                if isinstance(value, dict):
                    arg_list.append(f"--{key}='{json.dumps(value)}'")
                else:
                    arg_list.append(f"--{key}={value}")
            arguments = " ".join(arg_list)
        entrypoint = f"python {program.entrypoint} {arguments}"

        # set program name so OT can use it as parent span name
        env_vars = {**(program.env_vars or {}), **{OT_PROGRAM_NAME: program.name}}

        job_id = self._job_client.submit_job(
            entrypoint=entrypoint,
            submission_id=f"qs_{uuid4()}",
            runtime_env={
                "working_dir": program.working_dir,
                "pip": program.dependencies,
                "env_vars": env_vars,
            },
        )
        return Job(job_id=job_id, job_client=self)


class GatewayJobClient(BaseJobClient):
    def __init__(self, host: str, token: str):
        self.host = host
        self._token = token

    def status(self, job_id: str):
        default_status = "Unknown"
        status = default_status
        response = requests.get(f"{self.host}/jobs/{job_id}/", headers={
                    'Authorization': f'Bearer {self._token}'
                })
        if response.ok:
            status = json.loads(response.text).get("status", default_status)
        else:
            logging.warning(f"Something went wrong during job status fetching. {response.text}")
        return status

    def stop(self, job_id: str):
        raise NotImplementedError

    def logs(self, job_id: str):
        raise NotImplementedError

    def result(self, job_id: str):
        result = None
        response = requests.get(f"{self.host}/jobs/{job_id}/", headers={
                    'Authorization': f'Bearer {self._token}'
                })
        if response.ok:
            result = json.loads(response.text).get("result", None)
        else:
            logging.warning(f"Something went wrong during job result fetching. {response.text}")
        return result


class Job:
    """Job."""

    def __init__(self, job_id: str, job_client: BaseJobClient):
        """Job class for async script execution.

        Args:
            job_id: if of the job
            job_client: job client
        """
        self.job_id = job_id
        self._job_client = job_client

    def status(self):
        """Returns status of the job."""
        return self._job_client.status(self.job_id)

    def stop(self):
        """Stops the job from running."""
        return self._job_client.stop(self.job_id)

    def logs(self) -> str:
        """Returns logs of the job."""
        return self._job_client.logs(self.job_id)

    def result(self):
        """Return results of the job."""
        return self._job_client.result(self.job_id)

    def __repr__(self):
        return f"<Job | {self.job_id}>"
