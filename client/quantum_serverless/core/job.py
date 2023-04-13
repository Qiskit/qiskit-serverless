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
from typing import Dict, Any
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
from quantum_serverless.utils.json import is_jsonable

RuntimeEnv = ray.runtime_env.RuntimeEnv


class BaseJobClient:
    """Base class for Job clients."""

    def run(self, quantum_function: Program) -> "Job":
        """Runs quantum function."""
        raise NotImplementedError

    def status(self, job_id: str):
        """Check status."""
        raise NotImplementedError

    def stop(self, job_id: str):
        """Stops job/quantum-function."""
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

    def run(self, quantum_function: Program):
        arguments = ""
        if quantum_function.arguments is not None:
            arg_list = []
            for key, value in quantum_function.arguments.items():
                if isinstance(value, dict):
                    arg_list.append(f"--{key}='{json.dumps(value)}'")
                else:
                    arg_list.append(f"--{key}={value}")
            arguments = " ".join(arg_list)
        entrypoint = f"python {quantum_function.entrypoint} {arguments}"

        # set quantum_function name so OT can use it as parent span name
        env_vars = {
            **(quantum_function.env_vars or {}),
            **{OT_PROGRAM_NAME: quantum_function.title},
        }

        job_id = self._job_client.submit_job(
            entrypoint=entrypoint,
            submission_id=f"qs_{uuid4()}",
            runtime_env={
                "working_dir": quantum_function.working_dir,
                "pip": quantum_function.dependencies,
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
        raise NotImplementedError

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
            result = json.loads(response.text).get("result", None)
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
