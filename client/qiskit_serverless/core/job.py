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
from abc import ABC, abstractmethod
import json
import logging
import os
import time
import warnings
from typing import ClassVar, Dict, Any, Literal, Optional, Union
from dataclasses import dataclass

import ray.runtime_env
import requests

from qiskit_ibm_runtime import QiskitRuntimeService

from qiskit_serverless.core.constants import (
    ENV_JOB_GATEWAY_INSTANCE,
    REQUESTS_TIMEOUT,
    ENV_JOB_GATEWAY_TOKEN,
    ENV_JOB_GATEWAY_HOST,
    ENV_JOB_ID_GATEWAY,
    ENV_GATEWAY_PROVIDER_VERSION,
    GATEWAY_PROVIDER_VERSION_DEFAULT,
    ENV_ACCESS_TRIAL,
)
from qiskit_serverless.exception import QiskitServerlessException
from qiskit_serverless.serializers.program_serializers import (
    QiskitObjectsEncoder,
    QiskitObjectsDecoder,
)
from qiskit_serverless.utils.http import get_headers
from qiskit_serverless.utils.json import is_jsonable

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


class JobService(ABC):
    """Provide access to job information"""

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
        """Returns logs of the job.
        Args:
            job_id: The job's logs
            include: rex expression finds match in the log line to be included
            exclude: rex expression finds match in the log line to be excluded
        """


PendingType = Literal["PENDING"]
RunningType = Literal["RUNNING"]
StoppedType = Literal["STOPPED"]
SucceededType = Literal["SUCCEEDED"]
FailedType = Literal["FAILED"]
QueuedType = Literal["QUEUED"]
# RUNNING statuses
MappingType = Literal["MAPPING"]
OptimizingHardwareType = Literal["OPTIMIZING_HARDWARE"]
WaitingQpuType = Literal["WAITING_QPU"]
ExecutingQpuType = Literal["EXECUTING_QPU"]
PostProcessingType = Literal["POST_PROCESSING"]


class Job:
    """Job."""

    PENDING: ClassVar[PendingType] = "PENDING"
    RUNNING: ClassVar[RunningType] = "RUNNING"
    STOPPED: ClassVar[StoppedType] = "STOPPED"
    SUCCEEDED: ClassVar[SucceededType] = "SUCCEEDED"
    FAILED: ClassVar[FailedType] = "FAILED"
    QUEUED: ClassVar[QueuedType] = "QUEUED"
    # RUNNING statuses
    MAPPING: ClassVar[MappingType] = "MAPPING"
    OPTIMIZING_HARDWARE: ClassVar[OptimizingHardwareType] = "OPTIMIZING_HARDWARE"
    WAITING_QPU: ClassVar[WaitingQpuType] = "WAITING_QPU"
    EXECUTING_QPU: ClassVar[ExecutingQpuType] = "EXECUTING_QPU"
    POST_PROCESSING: ClassVar[PostProcessingType] = "POST_PROCESSING"

    def __init__(
        self,
        job_id: str,
        job_service: JobService,
        raw_data: Optional[Dict[str, Any]] = None,
    ):
        """Job class for async script execution.

        Args:
            job_id: if of the job
            client: client
        """
        self.job_id = job_id
        self._job_service = job_service
        self.raw_data = raw_data or {}

    def status(self):
        """Returns status of the job."""
        return _map_status_to_serverless(self._job_service.status(self.job_id))

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
        return self._job_service.stop(self.job_id, service=service)

    def logs(self) -> str:
        """Returns logs of the job."""
        return self._job_service.logs(self.job_id)

    def filtered_logs(self, **kwargs) -> str:
        """Returns logs of the job.
        Args:
            include: rex expression finds match in the log line to be included
            exclude: rex expression finds match in the log line to be excluded
        """
        return self._job_service.filtered_logs(job_id=self.job_id, **kwargs)

    def error_message(self):
        """Returns the execution error message."""
        return self._job_service.result(self.job_id) if self.status() == "ERROR" else ""

    def result(self, wait=True, cadence=30, verbose=False, maxwait=0):
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
        results = self._job_service.result(self.job_id)

        if self.status() == "ERROR":
            raise QiskitServerlessException(results)

        if isinstance(results, str):
            try:
                results = json.loads(results, cls=QiskitObjectsDecoder)
            except json.JSONDecodeError:
                logging.warning("Error during results decoding.")

        return results

    def in_terminal_state(self) -> bool:
        """Checks if job is in terminal state"""
        terminal_status = ["CANCELED", "DONE", "ERROR"]
        return self.status() in terminal_status

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

    instance = os.environ.get(ENV_JOB_GATEWAY_INSTANCE, None)

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
        headers=get_headers(token=token, instance=instance),
        timeout=REQUESTS_TIMEOUT,
    )
    if not response.ok:
        sanitized = response.text.replace("\n", "").replace("\r", "")
        logging.warning("Something went wrong: %s", sanitized)

    return response.ok


def update_status(status: str):
    """Update sub status."""

    version = os.environ.get(ENV_GATEWAY_PROVIDER_VERSION)
    if version is None:
        version = GATEWAY_PROVIDER_VERSION_DEFAULT

    token = os.environ.get(ENV_JOB_GATEWAY_TOKEN)
    if token is None:
        logging.warning(
            "'sub_status' cannot be updated since"
            "there is no information about the"
            "authorization token in the environment."
        )
        return False

    instance = os.environ.get(ENV_JOB_GATEWAY_INSTANCE, None)

    url = (
        f"{os.environ.get(ENV_JOB_GATEWAY_HOST)}/"
        f"api/{version}/jobs/{os.environ.get(ENV_JOB_ID_GATEWAY)}/sub_status/"
    )
    response = requests.patch(
        url,
        data={"sub_status": status},
        headers=get_headers(token=token, instance=instance),
        timeout=REQUESTS_TIMEOUT,
    )
    if not response.ok:
        sanitized = response.text.replace("\n", "").replace("\r", "")
        logging.warning("Something went wrong: %s", sanitized)

    return response.ok


def _map_status_to_serverless(status: str) -> str:
    """Map a status string from job client to the Qiskit terminology."""
    status_map = {
        Job.PENDING: "INITIALIZING",
        Job.RUNNING: "RUNNING",
        Job.STOPPED: "CANCELED",
        Job.SUCCEEDED: "DONE",
        Job.FAILED: "ERROR",
        Job.QUEUED: "QUEUED",
        Job.MAPPING: "RUNNING: MAPPING",
        Job.OPTIMIZING_HARDWARE: "RUNNING: OPTIMIZING_FOR_HARDWARE",
        Job.WAITING_QPU: "RUNNING: WAITING_FOR_QPU",
        Job.EXECUTING_QPU: "RUNNING: EXECUTING_QPU",
        Job.POST_PROCESSING: "RUNNING: POST_PROCESSING",
    }

    try:
        return status_map[status]
    except KeyError:
        return status


def is_running_in_serverless() -> bool:
    """Return ``True`` if running as a Qiskit serverless program, ``False`` otherwise."""
    return ENV_JOB_ID_GATEWAY in os.environ


def is_trial() -> bool:
    """Return ``True`` if Job is running in trial mode, ``False`` otherwise."""
    return os.getenv(ENV_ACCESS_TRIAL) == "True"
