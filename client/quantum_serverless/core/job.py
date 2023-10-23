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
import time
from pathlib import Path
from typing import Dict, Any, Optional, List, Union
from uuid import uuid4

import ray.runtime_env
import requests
from ray.dashboard.modules.job.sdk import JobSubmissionClient

from opentelemetry import trace

from quantum_serverless.core.constants import (
    OT_PROGRAM_NAME,
    REQUESTS_TIMEOUT,
    ENV_JOB_GATEWAY_TOKEN,
    ENV_JOB_GATEWAY_HOST,
    ENV_JOB_ID_GATEWAY,
    ENV_GATEWAY_PROVIDER_VERSION,
    GATEWAY_PROVIDER_VERSION_DEFAULT,
    MAX_ARTIFACT_FILE_SIZE_MB,
    ENV_JOB_ARGUMENTS,
)
from quantum_serverless.core.program import Program
from quantum_serverless.exception import QuantumServerlessException
from quantum_serverless.serializers.program_serializers import (
    QiskitObjectsEncoder,
    QiskitObjectsDecoder,
)
from quantum_serverless.utils.json import is_jsonable, safe_json_request

RuntimeEnv = ray.runtime_env.RuntimeEnv


class BaseJobClient:
    """Base class for Job clients."""

    def run(
        self, program: Program, arguments: Optional[Dict[str, Any]] = None
    ) -> "Job":
        """Runs program."""
        raise NotImplementedError

    def upload(self, program: Program):
        """Uploads program."""
        raise NotImplementedError

    def run_existing(
        self, program: Union[str, Program], arguments: Optional[Dict[str, Any]] = None
    ):
        """Executes existing program."""
        raise NotImplementedError

    def get(self, job_id) -> Optional["Job"]:
        """Returns job by job id"""
        raise NotImplementedError

    def list(self, **kwargs) -> List["Job"]:
        """Returns list of jobs."""
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

    def get_programs(self, **kwargs):
        """Returns list of programs."""
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

    def get(self, job_id) -> Optional["Job"]:
        return Job(self._job_client.get_job_info(job_id).job_id, job_client=self)

    def list(self, **kwargs) -> List["Job"]:
        return [
            Job(job.job_id, job_client=self) for job in self._job_client.list_jobs()
        ]

    def run(self, program: Program, arguments: Optional[Dict[str, Any]] = None):
        arguments = arguments or {}
        entrypoint = f"python {program.entrypoint}"

        # set program name so OT can use it as parent span name
        env_vars = {
            **(program.env_vars or {}),
            **{OT_PROGRAM_NAME: program.title},
            **{ENV_JOB_ARGUMENTS: json.dumps(arguments, cls=QiskitObjectsEncoder)},
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

    def upload(self, program: Program):
        raise NotImplementedError("Upload is not available for RayJobClient.")

    def run_existing(
        self, program: Union[str, Program], arguments: Optional[Dict[str, Any]] = None
    ):
        raise NotImplementedError("Run existing is not available for RayJobClient.")


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

    def run(  # pylint: disable=too-many-locals
        self, program: Program, arguments: Optional[Dict[str, Any]] = None
    ) -> "Job":
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("job.run") as span:
            span.set_attribute("program", program.title)
            span.set_attribute("arguments", str(arguments))

            url = f"{self.host}/api/{self.version}/programs/run/"
            artifact_file_path = os.path.join(program.working_dir, "artifact.tar")

            # check if entrypoint exists
            if not os.path.exists(
                os.path.join(program.working_dir, program.entrypoint)
            ):
                raise QuantumServerlessException(
                    f"Entrypoint file [{program.entrypoint}] does not exist "
                    f"in [{program.working_dir}] working directory."
                )

            with tarfile.open(artifact_file_path, "w") as tar:
                for filename in os.listdir(program.working_dir):
                    fpath = os.path.join(program.working_dir, filename)
                    tar.add(fpath, arcname=filename)

            # check file size
            size_in_mb = Path(artifact_file_path).stat().st_size / 1024**2
            if size_in_mb > MAX_ARTIFACT_FILE_SIZE_MB:
                raise QuantumServerlessException(
                    f"{artifact_file_path} is {int(size_in_mb)} Mb, "
                    f"which is greater than {MAX_ARTIFACT_FILE_SIZE_MB} allowed. "
                    f"Try to reduce size of `working_dir`."
                )

            with open(artifact_file_path, "rb") as file:
                response_data = safe_json_request(
                    request=lambda: requests.post(
                        url=url,
                        data={
                            "title": program.title,
                            "entrypoint": program.entrypoint,
                            "arguments": json.dumps(
                                arguments or {}, cls=QiskitObjectsEncoder
                            ),
                            "dependencies": json.dumps(program.dependencies or []),
                        },
                        files={"artifact": file},
                        headers={"Authorization": f"Bearer {self._token}"},
                        timeout=REQUESTS_TIMEOUT,
                    )
                )
                job_id = response_data.get("id")
                span.set_attribute("job.id", job_id)

            if os.path.exists(artifact_file_path):
                os.remove(artifact_file_path)

        return Job(job_id, job_client=self)

    def upload(self, program: Program):
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("job.run") as span:
            span.set_attribute("program", program.title)

            url = f"{self.host}/api/{self.version}/programs/upload/"
            artifact_file_path = os.path.join(program.working_dir, "artifact.tar")

            # check if entrypoint exists
            if not os.path.exists(
                os.path.join(program.working_dir, program.entrypoint)
            ):
                raise QuantumServerlessException(
                    f"Entrypoint file [{program.entrypoint}] does not exist "
                    f"in [{program.working_dir}] working directory."
                )

            with tarfile.open(artifact_file_path, "w") as tar:
                for filename in os.listdir(program.working_dir):
                    fpath = os.path.join(program.working_dir, filename)
                    tar.add(fpath, arcname=filename)

            # check file size
            size_in_mb = Path(artifact_file_path).stat().st_size / 1024**2
            if size_in_mb > MAX_ARTIFACT_FILE_SIZE_MB:
                raise QuantumServerlessException(
                    f"{artifact_file_path} is {int(size_in_mb)} Mb, "
                    f"which is greater than {MAX_ARTIFACT_FILE_SIZE_MB} allowed. "
                    f"Try to reduce size of `working_dir`."
                )

            with open(artifact_file_path, "rb") as file:
                response_data = safe_json_request(
                    request=lambda: requests.post(
                        url=url,
                        data={
                            "title": program.title,
                            "entrypoint": program.entrypoint,
                            "arguments": json.dumps({}),
                            "dependencies": json.dumps(program.dependencies or []),
                        },
                        files={"artifact": file},
                        headers={"Authorization": f"Bearer {self._token}"},
                        timeout=REQUESTS_TIMEOUT,
                    )
                )
                program_title = response_data.get("title", "na")
                span.set_attribute("program.title", program_title)

            if os.path.exists(artifact_file_path):
                os.remove(artifact_file_path)

        return program_title

    def run_existing(
        self, program: Union[str, Program], arguments: Optional[Dict[str, Any]] = None
    ):
        if isinstance(program, Program):
            title = program.title
        else:
            title = str(program)

        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("job.run_existing") as span:
            span.set_attribute("program", title)
            span.set_attribute("arguments", str(arguments))

            url = f"{self.host}/api/{self.version}/programs/run_existing/"

            response_data = safe_json_request(
                request=lambda: requests.post(
                    url=url,
                    data={
                        "title": title,
                        "arguments": json.dumps(
                            arguments or {}, cls=QiskitObjectsEncoder
                        ),
                    },
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=REQUESTS_TIMEOUT,
                )
            )
            job_id = response_data.get("id")
            span.set_attribute("job.id", job_id)

        return Job(job_id, job_client=self)

    def status(self, job_id: str):
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("job.status"):
            default_status = "Unknown"
            response_data = safe_json_request(
                request=lambda: requests.get(
                    f"{self.host}/api/{self.version}/jobs/{job_id}/",
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=REQUESTS_TIMEOUT,
                )
            )

        return response_data.get("status", default_status)

    def stop(self, job_id: str):
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("job.stop"):
            response_data = safe_json_request(
                request=lambda: requests.post(
                    f"{self.host}/api/{self.version}/jobs/{job_id}/stop/",
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=REQUESTS_TIMEOUT,
                )
            )

        return response_data.get("message")

    def logs(self, job_id: str):
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("job.logs"):
            response_data = safe_json_request(
                request=lambda: requests.get(
                    f"{self.host}/api/{self.version}/jobs/{job_id}/logs/",
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=REQUESTS_TIMEOUT,
                )
            )
        return response_data.get("logs")

    def result(self, job_id: str):
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("job.result"):
            response_data = safe_json_request(
                request=lambda: requests.get(
                    f"{self.host}/api/{self.version}/jobs/{job_id}/",
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=REQUESTS_TIMEOUT,
                )
            )
        return json.loads(
            response_data.get("result", "{}") or "{}", cls=QiskitObjectsDecoder
        )

    def get(self, job_id) -> Optional["Job"]:
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("job.get"):
            url = f"{self.host}/api/{self.version}/jobs/{job_id}/"
            response_data = safe_json_request(
                request=lambda: requests.get(
                    url,
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=REQUESTS_TIMEOUT,
                )
            )

            job = None
            job_id = response_data.get("id")
            if job_id is not None:
                job = Job(
                    job_id=response_data.get("id"),
                    job_client=self,
                )

        return job

    def list(self, **kwargs) -> List["Job"]:
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("job.list"):
            limit = kwargs.get("limit", 10)
            offset = kwargs.get("offset", 0)
            response_data = safe_json_request(
                request=lambda: requests.get(
                    f"{self.host}/api/{self.version}/jobs/?limit={limit}&offset={offset}",
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=REQUESTS_TIMEOUT,
                )
            )
        return [
            Job(job.get("id"), job_client=self, raw_data=job)
            for job in response_data.get("results", [])
        ]

    def get_programs(self, **kwargs):
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("program.list"):
            limit = kwargs.get("limit", 10)
            offset = kwargs.get("offset", 0)
            response_data = safe_json_request(
                request=lambda: requests.get(
                    f"{self.host}/api/{self.version}/programs/?limit={limit}&offset={offset}",
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=REQUESTS_TIMEOUT,
                )
            )
        return [
            Program(program.get("title"), raw_data=program)
            for program in response_data.get("results", [])
        ]


class Job:
    """Job."""

    def __init__(
        self,
        job_id: str,
        job_client: BaseJobClient,
        raw_data: Optional[Dict[str, Any]] = None,
    ):
        """Job class for async script execution.

        Args:
            job_id: if of the job
            job_client: job client
        """
        self.job_id = job_id
        self._job_client = job_client
        self.raw_data = raw_data or {}

    def status(self):
        """Returns status of the job."""
        return self._job_client.status(self.job_id)

    def stop(self):
        """Stops the job from running."""
        return self._job_client.stop(self.job_id)

    def logs(self) -> str:
        """Returns logs of the job."""
        return self._job_client.logs(self.job_id)

    def result(self, wait=True, cadence=5, verbose=False):
        """Return results of the job.
        Args:
            wait: flag denoting whether to wait for the
                job result to be populated before returning
            cadence: time to wait between checking if job has
                been terminated
            verbose: flag denoting whether to log a heartbeat
                while waiting for job result to populate
        """
        if wait:
            if verbose:
                logging.info("Waiting for job result.")
            while not self._in_terminal_state():
                time.sleep(cadence)
                if verbose:
                    logging.info(".")

        # Retrieve the results. If they're string format, try to decode to a dictionary.
        results = self._job_client.result(self.job_id)
        if isinstance(results, str):
            try:
                results = json.loads(results, cls=QiskitObjectsDecoder)
            except json.JSONDecodeError as exception:
                logging.warning("Error during results decoding. Details: %s", exception)

        return results

    def _in_terminal_state(self) -> bool:
        """Checks if job is in terminal state"""
        terminal_states = ["STOPPED", "SUCCEEDED", "FAILED"]
        return self.status() in terminal_states

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
            "Results will be saved as logs since"
            "there is no information about the"
            "authorization token in the environment."
        )
        logging.info("Result: %s", result)
        return False

    if not is_jsonable(result, cls=QiskitObjectsEncoder):
        logging.warning("Object passed is not json serializable.")
        return False

    url = (
        f"{os.environ.get(ENV_JOB_GATEWAY_HOST)}/"
        f"api/{version}/jobs/{os.environ.get(ENV_JOB_ID_GATEWAY)}/result/"
    )
    response = requests.post(
        url,
        data={"result": json.dumps(result or {}, cls=QiskitObjectsEncoder)},
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUESTS_TIMEOUT,
    )
    if not response.ok:
        logging.warning("Something went wrong: %s", response.text)

    return response.ok
