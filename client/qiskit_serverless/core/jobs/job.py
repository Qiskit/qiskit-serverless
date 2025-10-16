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
import dataclasses
import json
import logging
import time
import warnings
from typing import ClassVar, Dict, Any, Literal, Optional
from dataclasses import dataclass

import ray.runtime_env

from qiskit_ibm_runtime import QiskitRuntimeService

from qiskit_serverless.exception import QiskitServerlessException
from qiskit_serverless.serializers.program_serializers import (
    QiskitObjectsDecoder,
)

from .job_service import JobService

RuntimeEnv = ray.runtime_env.RuntimeEnv


@dataclass
class Configuration:  # pylint: disable=too-many-instance-attributes
    """Program Configuration.

    Args:
        workers: number of worker pod when auto scaling is NOT enabled
        auto_scaling: set True to enable auto scaling of the workers
        min_workers: minimum number of workers when auto scaling is enabled
        max_workers: maximum number of workers when auto scaling is enabled
    """

    workers: Optional[int] = None
    min_workers: Optional[int] = None
    max_workers: Optional[int] = None
    auto_scaling: Optional[bool] = False


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


@dataclass
class Job:
    """Job

    Args:
        id: database identifier
        job_service: service that provide access to API
        raw_data: any
        workflow_job_id: the workflow that contains this job.
        workflow_function: the function that generated the workflow.
        depends_on: the job that should finish before this starts
    """

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

    id: str
    job_service: JobService
    raw_data: Optional[Dict[str, Any]] = None
    workflow_id: Optional[str] = None
    workflow_function: Optional[str] = None
    depends_on: Optional[str] = None

    @classmethod
    def from_json(cls, data: Dict[str, Any]):
        """Reconstructs QiskitPattern from dictionary."""
        field_names = set(f.name for f in dataclasses.fields(Job))
        data["raw_data"] = data
        return Job(**{k: v for k, v in data.items() if k in field_names})

    def status(self):
        """Returns status of the job."""
        return _map_status_to_serverless(self.job_service.status(self.id))

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
        return self.job_service.stop(self.id, service=service)

    def logs(self) -> str:
        """Returns logs of the job."""
        return self.job_service.logs(self.id)

    def filtered_logs(self, **kwargs) -> str:
        """Returns logs of the job.
        Args:
            include: regex expression finds matching line in the log to be included
            exclude: regex expression finds matching line in the log to be excluded
        """
        return self.job_service.filtered_logs(job_id=self.id, **kwargs)

    def error_message(self):
        """Returns the execution error message."""
        error = self.job_service.result(self.id) if self.status() == "ERROR" else ""

        if isinstance(error, str):
            try:
                return error.strip('"').encode().decode("unicode_escape")
            except UnicodeDecodeError:
                logging.warning("Error decoding error message, returning raw message.")

        return error

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
        results = self.job_service.result(self.id)

        if self.status() == "ERROR":
            if results:
                raise QiskitServerlessException(results)

            # If no result returned (common with import errors),
            # try to match on error trace in logs to point to source of error
            raise QiskitServerlessException(
                self.filtered_logs(include=r"(?i)error|exception")
            )

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
        return f"<Job | {self.id}>"


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
