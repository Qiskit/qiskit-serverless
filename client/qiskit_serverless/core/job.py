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
Provider (:mod:`qiskit_serverless.core.job`)
=============================================

.. currentmodule:: qiskit_serverless.core.job

Qiskit Serverless job
======================

.. autosummary::
    :toctree: ../stubs/

    RuntimeEnv
    Job
"""
# pylint: disable=duplicate-code
import json
import logging
import os
import re
import tarfile
import time
import sys
import warnings
from pathlib import Path
from typing import Dict, Any, Optional, List, Union
from uuid import uuid4
from dataclasses import asdict, dataclass

import subprocess
from subprocess import Popen

import ray.runtime_env
import requests
from ray.dashboard.modules.job.sdk import JobSubmissionClient

from opentelemetry import trace
from qiskit_ibm_runtime import QiskitRuntimeService

from qiskit_serverless.core.constants import (
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

from qiskit_serverless.core.function import QiskitFunction
from qiskit_serverless.exception import QiskitServerlessException
from qiskit_serverless.serializers.program_serializers import (
    QiskitObjectsEncoder,
    QiskitObjectsDecoder,
)
from qiskit_serverless.utils.json import is_jsonable, safe_json_request
from qiskit_serverless.utils.formatting import format_provider_name_and_title

RuntimeEnv = ray.runtime_env.RuntimeEnv


@dataclass
class Configuration:  # pylint: disable=too-many-instance-attributes
    """Program Configuration.

    Args:
        workers: number of worker pod when auto scaling is NOT enabled
        auto_scaling: set True to enable auto scating of the workers
        min_workers: minimum number of workers when auto scaling is enabled
        max_workers: maxmum number of workers when auto scaling is enabled
    """

    workers: Optional[int] = None
    min_workers: Optional[int] = None
    max_workers: Optional[int] = None
    auto_scaling: Optional[bool] = False


class BaseJobClient:
    """Base class for Job clients."""

    def run(
        self,
        program: Union[str, QiskitFunction],
        provider: Optional[str] = None,
        arguments: Optional[Dict[str, Any]] = None,
        config: Optional[Configuration] = None,
    ) -> "Job":
        """Runs program."""
        raise NotImplementedError

    def upload(self, program: QiskitFunction):
        """Uploads program."""
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

    def stop(self, job_id: str, service: Optional[QiskitRuntimeService] = None):
        """Stops job/program."""
        raise NotImplementedError

    def logs(self, job_id: str):
        """Return logs."""
        raise NotImplementedError

    def filtered_logs(self, job_id: str, **kwargs):
        """Return filtered logs."""
        raise NotImplementedError

    def result(self, job_id: str):
        """Return results."""
        raise NotImplementedError

    def get_programs(self, **kwargs):
        """Returns list of programs."""
        raise NotImplementedError

    def get_program(
        self, title: str, provider: Optional[str] = None
    ) -> Optional[QiskitFunction]:
        """Returns program based on parameters."""
        raise NotImplementedError

    def get_jobs(self, title: str, provider: Optional[str] = None):
        """Returns job ids of executed program based on parameters."""
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
        return self._job_client.get_job_status(job_id).value

    def stop(self, job_id: str, service: Optional[QiskitRuntimeService] = None):
        return self._job_client.stop_job(job_id)

    def logs(self, job_id: str):
        return self._job_client.get_job_logs(job_id)

    def filtered_logs(self, job_id: str, **kwargs):
        raise NotImplementedError

    def result(self, job_id: str):
        return self.logs(job_id)

    def get(self, job_id) -> Optional["Job"]:
        return Job(self._job_client.get_job_info(job_id).job_id, job_client=self)

    def list(self, **kwargs) -> List["Job"]:
        return [
            Job(job.job_id, job_client=self) for job in self._job_client.list_jobs()
        ]

    def run(
        self,
        program: Union[str, QiskitFunction],
        provider: Optional[str] = None,
        arguments: Optional[Dict[str, Any]] = None,
        config: Optional[Configuration] = None,
    ):
        if not isinstance(program, QiskitFunction):
            warnings.warn(
                "`run` doesn't support program str yet. "
                "Send a QiskitFunction instead. "
            )
            return NotImplementedError

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

    def upload(self, program: QiskitFunction):
        raise NotImplementedError("Upload is not available for RayJobClient.")


class LocalJobClient(BaseJobClient):
    """LocalJobClient."""

    def __init__(self):
        """Local job client.

        Args:
        """
        self._jobs = {}
        self._patterns = []

    def status(self, job_id: str):
        return self._jobs[job_id]["status"]

    def stop(self, job_id: str, service: Optional[QiskitRuntimeService] = None):
        """Stops job/program."""
        return f"job:{job_id} has already stopped"

    def logs(self, job_id: str):
        return self._jobs[job_id]["logs"]

    def result(self, job_id: str):
        return self._jobs[job_id]["result"]

    def get(self, job_id) -> Optional["Job"]:
        return self._jobs[job_id]["job"]

    def list(self, **kwargs) -> List["Job"]:
        return [job["job"] for job in list(self._jobs.values())]

    def filtered_logs(self, job_id: str, **kwargs):
        """Return filtered logs."""
        raise NotImplementedError

    def run(  # pylint: disable=too-many-locals
        self,
        program: Union[str, QiskitFunction],
        provider: Optional[str] = None,
        arguments: Optional[Dict[str, Any]] = None,
        config: Optional[Configuration] = None,
    ):
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

        job = Job(job_id=str(uuid4()), job_client=self)
        entry = {"status": status, "logs": output, "result": result, "job": job}
        self._jobs[job.job_id] = entry
        return job

    def upload(self, program: QiskitFunction):
        # check if entrypoint exists
        if not os.path.exists(os.path.join(program.working_dir, program.entrypoint)):
            raise QiskitServerlessException(
                f"Entrypoint file [{program.entrypoint}] does not exist "
                f"in [{program.working_dir}] working directory."
            )
        self._patterns.append(
            {
                "title": program.title,
                "provider": program.provider,
                "entrypoint": program.entrypoint,
                "working_dir": program.working_dir,
                "env_vars": program.env_vars,
                "arguments": json.dumps({}),
                "dependencies": json.dumps(program.dependencies or []),
            }
        )
        return program.title

    def get_programs(self, **kwargs):
        """Returns list of programs."""
        return [
            QiskitFunction(
                program.get("title"),
                provider=program.get("provider", None),
                raw_data=program,
                job_client=self,
            )
            for program in self._patterns
        ]

    def get_program(
        self, title: str, provider: Optional[str] = None
    ) -> Optional[QiskitFunction]:
        """Returns program based on parameters."""
        all_programs = {
            program.get("title"): QiskitFunction(
                program.get("title"),
                provider=program.get("provider", None),
                raw_data=program,
                job_client=self,
            )
            for program in self._patterns
        }
        return all_programs.get("title")


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
        self,
        program: Union[str, QiskitFunction],
        provider: Optional[str] = None,
        arguments: Optional[Dict[str, Any]] = None,
        config: Optional[Configuration] = None,
    ) -> "Job":
        if isinstance(program, QiskitFunction):
            title = program.title
        else:
            title = str(program)

        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("job.run") as span:
            span.set_attribute("program", title)
            span.set_attribute("provider", provider)
            span.set_attribute("arguments", str(arguments))

            url = f"{self.host}/api/{self.version}/programs/run/"

            data = {
                "title": title,
                "provider": provider,
                "arguments": json.dumps(arguments or {}, cls=QiskitObjectsEncoder),
            }  # type: Dict[str, Any]
            if config:
                data["config"] = asdict(config)
            else:
                data["config"] = asdict(Configuration())

            response_data = safe_json_request(
                request=lambda: requests.post(
                    url=url,
                    json=data,
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=REQUESTS_TIMEOUT,
                )
            )
            job_id = response_data.get("id")
            span.set_attribute("job.id", job_id)

        return Job(job_id, job_client=self)

    def upload(self, program: QiskitFunction):
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("job.run") as span:
            span.set_attribute("program", program.title)
            url = f"{self.host}/api/{self.version}/programs/upload/"

            if program.image is not None:
                # upload function with custom image
                program_title = _upload_with_docker_image(
                    program=program, url=url, token=self._token, span=span
                )
            elif program.entrypoint is not None:
                # upload funciton with artifact
                program_title = _upload_with_artifact(
                    program=program, url=url, token=self._token, span=span
                )
            else:
                raise QiskitServerlessException(
                    "Function must either have `entrypoint` or `image` specified."
                )

        return program_title

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

    def stop(self, job_id: str, service: Optional[QiskitRuntimeService] = None):
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("job.stop"):
            if service:
                data = {
                    "service": json.dumps(service, cls=QiskitObjectsEncoder),
                }
            else:
                data = {
                    "service": None,
                }
            response_data = safe_json_request(
                request=lambda: requests.post(
                    f"{self.host}/api/{self.version}/jobs/{job_id}/stop/",
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=REQUESTS_TIMEOUT,
                    json=data,
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

    def filtered_logs(self, job_id: str, **kwargs):
        all_logs = self.logs(job_id=job_id)
        included = ""
        include = kwargs.get("include")
        if include is not None:
            for line in all_logs.split("\n"):
                if re.search(include, line) is not None:
                    included = included + line + "\n"
        else:
            included = all_logs

        excluded = ""
        exclude = kwargs.get("exclude")
        if exclude is not None:
            for line in included.split("\n"):
                if line != "" and re.search(exclude, line) is None:
                    excluded = excluded + line + "\n"
        else:
            excluded = included
        return excluded

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
            kwargs["limit"] = limit
            offset = kwargs.get("offset", 0)
            kwargs["offset"] = offset
            response_data = safe_json_request(
                request=lambda: requests.get(
                    f"{self.host}/api/{self.version}/jobs",
                    params=kwargs,
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
            response_data = safe_json_request(
                request=lambda: requests.get(
                    f"{self.host}/api/{self.version}/programs",
                    headers={"Authorization": f"Bearer {self._token}"},
                    params=kwargs,
                    timeout=REQUESTS_TIMEOUT,
                )
            )
        return [
            QiskitFunction(
                program.get("title"),
                provider=program.get("provider", None),
                raw_data=program,
                job_client=self,
                description=program.get("description"),
            )
            for program in response_data
        ]

    def get_program(
        self, title: str, provider: Optional[str] = None
    ) -> Optional[QiskitFunction]:
        """Returns program based on parameters."""
        provider, title = format_provider_name_and_title(
            request_provider=provider, title=title
        )

        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("program.get_by_title"):
            response_data = safe_json_request(
                request=lambda: requests.get(
                    f"{self.host}/api/{self.version}/programs/get_by_title/{title}",
                    headers={"Authorization": f"Bearer {self._token}"},
                    params={"provider": provider},
                    timeout=REQUESTS_TIMEOUT,
                )
            )
            return QiskitFunction(
                response_data.get("title"),
                provider=response_data.get("provider", None),
                raw_data=response_data,
                job_client=self,
            )

    def get_jobs(self, title: str, provider: Optional[str] = None):
        """Returns job ids executed the program based on parameters."""
        provider, title = format_provider_name_and_title(
            request_provider=provider, title=title
        )

        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("program.get_by_title"):
            response_data = safe_json_request(
                request=lambda: requests.get(
                    f"{self.host}/api/{self.version}/programs/get_by_title/{title}",
                    headers={"Authorization": f"Bearer {self._token}"},
                    params={"provider": provider},
                    timeout=REQUESTS_TIMEOUT,
                )
            )
            program_id = response_data.get("id", None)
            if not program_id:
                return None
            response_data = safe_json_request(
                request=lambda: requests.get(
                    f"{self.host}/api/{self.version}/programs/{program_id}/get_jobs/",
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=REQUESTS_TIMEOUT,
                )
            )
            return response_data


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
        return _map_status_to_serverless(self._job_client.status(self.job_id))

    def stop(self, service: Optional[QiskitRuntimeService] = None):
        """Stops the job from running."""
        warnings.warn(
            "`stop` method has been deprecated. "
            "And will be removed in future releases. "
            "Please, use `cancel` instead.",
            DeprecationWarning,
        )
        return self.cancel(service)

    def cancel(self, service: Optional[QiskitRuntimeService] = None):
        """Cancels the job."""
        return self._job_client.stop(self.job_id, service=service)

    def logs(self) -> str:
        """Returns logs of the job."""
        return self._job_client.logs(self.job_id)

    def filtered_logs(self, **kwargs) -> str:
        """Returns logs of the job.
        Args:
            include: rex expression finds match in the log line to be included
            exclude: rex expression finds match in the log line to be excluded
        """
        return self._job_client.filtered_logs(job_id=self.job_id, **kwargs)

    def result(self, wait=True, cadence=5, verbose=False, maxwait=0):
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
            count = 0
            while not self.in_terminal_state() and (maxwait == 0 or count < maxwait):
                count += 1
                time.sleep(cadence)
                if verbose:
                    logging.info(count)

        # Retrieve the results. If they're string format, try to decode to a dictionary.
        results = self._job_client.result(self.job_id)
        if isinstance(results, str):
            try:
                results = json.loads(results, cls=QiskitObjectsDecoder)
            except json.JSONDecodeError:
                logging.warning("Error during results decoding.")

        return results

    def in_terminal_state(self) -> bool:
        """Checks if job is in terminal state"""
        terminal_states = ["CANCELED", "DONE", "ERROR"]
        return self.status() in terminal_states

    def __repr__(self):
        return f"<Job | {self.job_id}>"


def save_result(result: Dict[str, Any]):
    """Saves job results.

    Note:
        data passed to save_result function
        must be json serializable (use dictionaries).
        Default serializer is compatible with
        IBM QiskitRuntime provider serializer.
        List of supported types
        [ndarray, QuantumCircuit, Parameter, ParameterExpression,
        NoiseModel, Instruction]. See full list via link.

    Links:
        Source of serializer:
        https://github.com/Qiskit/qiskit-ibm-runtime/blob/0.14.0/qiskit_ibm_runtime/utils/json.py#L197

    Example:
        >>> # save dictionary
        >>> save_result({"key": "value"})
        >>> # save circuit
        >>> circuit: QuantumCircuit = ...
        >>> save_result({"circuit": circuit})
        >>> # save primitives data
        >>> quasi_dists = Sampler.run(circuit).result().quasi_dists
        >>> # {"1x0": 0.1, ...}
        >>> save_result(quasi_dists)

    Args:
        result: data that will be accessible from job handler `.result()` method.
    """

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
        result_record = json.dumps(result or {}, cls=QiskitObjectsEncoder)
        print(f"\nSaved Result:{result_record}:End Saved Result\n")
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
        sanitized = response.text.replace("\n", "").replace("\r", "")
        logging.warning("Something went wrong: %s", sanitized)

    return response.ok


def _map_status_to_serverless(status: str) -> str:
    """Map a status string from job client to the Qiskit terminology."""
    status_map = {
        "PENDING": "INITIALIZING",
        "RUNNING": "RUNNING",
        "STOPPED": "CANCELED",
        "SUCCEEDED": "DONE",
        "FAILED": "ERROR",
        "QUEUED": "QUEUED",
    }

    try:
        return status_map[status]
    except KeyError:
        return status


def _upload_with_docker_image(
    program: QiskitFunction, url: str, token: str, span: Any
) -> str:
    """Uploads function with custom docker image.

    Args:
        program (QiskitFunction): function instance
        url (str): upload gateway url
        token (str): auth token
        span (Any): tracing span

    Returns:
        str: uploaded function name
    """
    response_data = safe_json_request(
        request=lambda: requests.post(
            url=url,
            data={
                "title": program.title,
                "provider": program.provider,
                "image": program.image,
                "arguments": json.dumps({}),
                "dependencies": json.dumps(program.dependencies or []),
                "env_vars": json.dumps(program.env_vars or {}),
                "description": program.description,
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUESTS_TIMEOUT,
        )
    )
    program_title = response_data.get("title", "na")
    program_provider = response_data.get("provider", "na")
    span.set_attribute("program.title", program_title)
    span.set_attribute("program.provider", program_provider)
    return program_title


def _upload_with_artifact(
    program: QiskitFunction, url: str, token: str, span: Any
) -> str:
    """Uploads function with artifact.

    Args:
        program (QiskitFunction): function instance
        url (str): endpoint for gateway upload
        token (str): auth token
        span (Any): tracing span

    Raises:
        QiskitServerlessException: if no entrypoint or size of artifact is too large.

    Returns:
        str: uploaded function name
    """
    artifact_file_path = os.path.join(program.working_dir, "artifact.tar")

    # check if entrypoint exists
    if (
        not os.path.exists(os.path.join(program.working_dir, program.entrypoint))
        or program.entrypoint[0] == "/"
    ):
        raise QiskitServerlessException(
            f"Entrypoint file [{program.entrypoint}] does not exist "
            f"in [{program.working_dir}] working directory."
        )

    try:
        with tarfile.open(artifact_file_path, "w") as tar:
            for filename in os.listdir(program.working_dir):
                fpath = os.path.join(program.working_dir, filename)
                tar.add(fpath, arcname=filename)

        # check file size
        size_in_mb = Path(artifact_file_path).stat().st_size / 1024**2
        if size_in_mb > MAX_ARTIFACT_FILE_SIZE_MB:
            raise QiskitServerlessException(
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
                        "provider": program.provider,
                        "entrypoint": program.entrypoint,
                        "arguments": json.dumps({}),
                        "dependencies": json.dumps(program.dependencies or []),
                        "env_vars": json.dumps(program.env_vars or {}),
                        "description": program.description,
                    },
                    files={"artifact": file},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=REQUESTS_TIMEOUT,
                )
            )
            program_title = response_data.get("title", "na")
            program_provider = response_data.get("provider", "na")
            span.set_attribute("program.title", program_title)
            span.set_attribute("program.provider", program_provider)
    except Exception as error:  # pylint: disable=broad-exception-caught
        raise QiskitServerlessException from error
    finally:
        if os.path.exists(artifact_file_path):
            os.remove(artifact_file_path)

    return program_title
