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
import os
import tarfile
from typing import Dict, Any, Optional
from uuid import uuid4

import ray.runtime_env
import requests
from ray.dashboard.modules.job.sdk import JobSubmissionClient

from quantum_serverless.core.constants import (
    OT_PROGRAM_NAME,
    REQUESTS_TIMEOUT,
    ENV_JOB_GATEWAY_TOKEN,
    ENV_JOB_GATEWAY_HOST,
    ENV_JOB_ID_GATEWAY,
    ENV_GATEWAY_PROVIDER_VERSION,
    GATEWAY_PROVIDER_VERSION_DEFAULT,
)
from quantum_serverless.core.program import Program
from quantum_serverless.exception import QuantumServerlessException
from quantum_serverless.serializers.program_serializers import QiskitObjectsEncoder
from quantum_serverless.utils.json import is_jsonable

RuntimeEnv = ray.runtime_env.RuntimeEnv


class BaseJobClient:
    """Base class for Job clients."""

    def run_program(
        self, program: Program, arguments: Optional[Dict[str, Any]] = None
    ) -> "Job":
        """Runs program."""
        raise NotImplementedError

    def status(self, job_id: str):
        """Check status."""
        raise NotImplementedError

    def stop(self, job_id: str):
        """Stops job/program."""
        raise NotImplementedError

    def logs(self, job_id: str):
        """Return logs."""
        raise NotImplementedError

    def result(self, job_id: str):
        """Return results."""
        raise NotImplementedError


class RayJobClient(BaseJobClient):
    """RayJobClient."""

    def __init__(self, client: JobSubmissionClient):
        """Ray job client.
        Wrapper around JobSubmissionClient

        Args:
            client: JobSubmissionClient
        """
        self._job_client = client

    def status(self, job_id: str):
        return self._job_client.get_job_status(job_id)

    def stop(self, job_id: str):
        return self._job_client.stop_job(job_id)

    def logs(self, job_id: str):
        return self._job_client.get_job_logs(job_id)

    def result(self, job_id: str):
        return self.logs(job_id)

    def run_program(self, program: Program, arguments: Optional[Dict[str, Any]] = None):
        arguments = arguments or {}
        arguments_string = ""
        if program.arguments is not None:
            arg_list = []
            for key, value in arguments.items():
                if isinstance(value, dict):
                    arg_list.append(f"--{key}='{json.dumps(value)}'")
                else:
                    arg_list.append(f"--{key}={value}")
            arguments_string = " ".join(arg_list)
        entrypoint = f"python {program.entrypoint} {arguments_string}"

        # set program name so OT can use it as parent span name
        env_vars = {
            **(program.env_vars or {}),
            **{OT_PROGRAM_NAME: program.title},
        }

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
    """GatewayJobClient."""

    def __init__(self, host: str, token: str, version: str):
        """Job client for Gateway service.

        Args:
            host: gateway host
            version: gateway version
            token: authorization token
        """
        self.host = host
        self.version = version
        self._token = token

    def run_program(
        self, program: Program, arguments: Optional[Dict[str, Any]] = None
    ) -> "Job":
        url = f"{self.host}/api/{self.version}/programs/run/"
        artifact_file_path = os.path.join(program.working_dir, "artifact.tar")

        with tarfile.open(artifact_file_path, "w") as tar:
            for filename in os.listdir(program.working_dir):
                fpath = os.path.join(program.working_dir, filename)
                tar.add(fpath, arcname=filename)

        with open(artifact_file_path, "rb") as file:
            response = requests.post(
                url=url,
                data={
                    "title": program.title,
                    "entrypoint": program.entrypoint,
                    "arguments": json.dumps(arguments or {}, cls=QiskitObjectsEncoder),
                    "dependencies": json.dumps(program.dependencies or []),
                },
                files={"artifact": file},
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=REQUESTS_TIMEOUT,
            )
            if not response.ok:
                raise QuantumServerlessException(
                    f"Something went wrong with program execution. {response.text}"
                )

            json_response = json.loads(response.text)
            job_id = json_response.get("id")

        if os.path.exists(artifact_file_path):
            os.remove(artifact_file_path)

        return Job(job_id, job_client=self)

    def status(self, job_id: str):
        default_status = "Unknown"
        status = default_status
        response = requests.get(
            f"{self.host}/api/{self.version}/jobs/{job_id}/",
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=REQUESTS_TIMEOUT,
        )
        if response.ok:
            status = json.loads(response.text).get("status", default_status)
        else:
            logging.warning(
                "Something went wrong during job status fetching. %s", response.text
            )
        return status

    def stop(self, job_id: str):
        message = ""
        response = requests.post(
            f"{self.host}/api/{self.version}/jobs/{job_id}/stop/",
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=REQUESTS_TIMEOUT,
        )
        if response.ok:
            message = json.loads(response.text).get("message", None)
        else:
            logging.warning(
                "Something went wrong during job stopping. %s", response.text
            )
        return message

    def logs(self, job_id: str):
        result = None
        response = requests.get(
            f"{self.host}/api/{self.version}/jobs/{job_id}/logs/",
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=REQUESTS_TIMEOUT,
        )
        if response.ok:
            result = json.loads(response.text).get("logs", None)
        else:
            logging.warning(
                "Something went wrong during job result fetching. %s", response.text
            )
        return result

    def result(self, job_id: str):
        result = None
        response = requests.get(
            f"{self.host}/api/{self.version}/jobs/{job_id}/",
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=REQUESTS_TIMEOUT,
        )
        if response.ok:
            json_result = json.loads(response.text).get("result", "{}")
            result = json.loads(json_result or "{}")
        else:
            logging.warning(
                "Something went wrong during job result fetching. %s", response.text
            )
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


def save_result(result: Dict[str, Any]):
    """Saves job results."""

    version = os.environ.get(ENV_GATEWAY_PROVIDER_VERSION)
    if version is None:
        version = GATEWAY_PROVIDER_VERSION_DEFAULT

    token = os.environ.get(ENV_JOB_GATEWAY_TOKEN)
    if token is None:
        logging.warning(
            "Results will not be saves as "
            "there are no information about "
            "authorization token in environment."
        )
        return False

    if not is_jsonable(result):
        logging.warning("Object passed is not json serializable.")
        return False

    url = (
        f"{os.environ.get(ENV_JOB_GATEWAY_HOST)}/"
        f"api/{version}/jobs/{os.environ.get(ENV_JOB_ID_GATEWAY)}/result/"
    )
    response = requests.post(
        url,
        json={"result": result},
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUESTS_TIMEOUT,
    )
    if not response.ok:
        logging.warning("Something went wrong: %s", response.text)

    return response.ok
