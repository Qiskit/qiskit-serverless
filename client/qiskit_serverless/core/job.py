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

    Job
"""

# pylint: disable=duplicate-code
from abc import ABC, abstractmethod
import json
import logging
import os
import random
import time
import warnings
from typing import ClassVar, Dict, Any, Literal, Optional, Tuple, Union
from dataclasses import dataclass

import requests

from qiskit_ibm_runtime import QiskitRuntimeService

from qiskit_serverless.core.constants import (
    ENV_JOB_GATEWAY_INSTANCE,
    QISKIT_IBM_CHANNEL,
    REQUESTS_TIMEOUT,
    ENV_JOB_GATEWAY_TOKEN,
    ENV_JOB_GATEWAY_HOST,
    ENV_JOB_ID_GATEWAY,
    ENV_GATEWAY_PROVIDER_VERSION,
    GATEWAY_PROVIDER_VERSION_DEFAULT,
    ENV_ACCESS_TRIAL,
    RESULTS_PATH,
)
from qiskit_serverless.exception import QiskitServerlessException
from qiskit_serverless.serializers.program_serializers import (
    QiskitObjectsEncoder,
    QiskitObjectsDecoder,
)
from qiskit_serverless.utils.errors import JobEvent, format_err_event, is_transient_error
from qiskit_serverless.utils.http import get_headers
from qiskit_serverless.utils.json import is_jsonable
from qiskit_serverless.utils import ServerlessRuntimeService

logger = logging.getLogger(__name__)

_FINAL_STATUSES = ("CANCELED", "DONE", "ERROR")
_BACKOFF_SECONDS = (1, 2, 4, 8, 16, 32, 60)
_BACKOFF_JITTER = 0.1
_RETRY_SECONDS = 300
_MIN_POLL_INTERVAL_SECONDS = 1


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


class JobService(ABC):
    """Provide access to job information"""

    @abstractmethod
    def status(self, job_id: str) -> str:
        """Check status."""

    @abstractmethod
    def stop(self, job_id: str, service: Optional[QiskitRuntimeService] = None) -> Union[str, bool]:
        """Stops job/program."""

    @abstractmethod
    def result(self, job_id: str) -> Any:
        """Return results."""

    @abstractmethod
    def logs(self, job_id: str) -> str:
        """Return logs."""

    @abstractmethod
    def provider_logs(self, job_id: str) -> str:
        """Return provider logs."""

    @abstractmethod
    def runtime_jobs(self, job_id: str, runtime_session: Optional[str] = None) -> list[str]:
        """Return associated runtime jobs."""

    @abstractmethod
    def runtime_sessions(self, job_id: str):
        """Returns associated runtime sessions if any."""

    @abstractmethod
    def filtered_logs(self, job_id: str, **kwargs) -> str:
        """Returns logs of the job.
        Args:
            job_id: The job's logs
            include: rex expression finds match in the log line to be included
            exclude: rex expression finds match in the log line to be excluded
        """

    def get_job_data(self, job_id: str) -> Optional[Dict[str, Any]]:  # pylint: disable=unused-argument
        """Return full job data dict, or None if not supported."""
        return None

    @abstractmethod
    def events(self, job_id: str, **kwargs) -> list[JobEvent]:
        """Returns events of the job.
        Args:
            job_id: The job id
        """


PendingType = Literal["PENDING"]
RunningType = Literal["RUNNING"]
StoppingType = Literal["STOPPING"]
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
    STOPPING: ClassVar[StoppingType] = "STOPPING"
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
        self._final_status: Optional[str] = None

    @property
    def fleet_id(self) -> Optional[str]:
        """Returns the Code Engine fleet ID for this job (Fleets runner only)."""
        return self.raw_data.get("fleet_id")

    def status(self):
        """Returns status of the job. A final status cannot change, so it is fetched only once."""
        if self._final_status is not None:
            return self._final_status
        status = self._fetch_status()
        if status in _FINAL_STATUSES:
            self._final_status = status
        return status

    def _fetch_status(self) -> str:
        fresh_data = self._job_service.get_job_data(self.job_id)
        if isinstance(fresh_data, dict):
            self.raw_data.update(fresh_data)
            raw_status = fresh_data.get("status")
            sub_status = fresh_data.get("sub_status")
            if raw_status == Job.RUNNING and sub_status is not None:
                return _map_status_from_serveless(sub_status)
            return _map_status_from_serveless(raw_status)
        return _map_status_from_serveless(self._job_service.status(self.job_id))

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

    def provider_logs(self) -> str:
        """Returns logs of the job."""
        return self._job_service.provider_logs(self.job_id)

    def runtime_jobs(self, runtime_session: Optional[str] = None) -> list[str]:
        """Returns associated runtime jobs if any."""
        return self._job_service.runtime_jobs(self.job_id, runtime_session=runtime_session)

    def runtime_sessions(self) -> list[str]:
        """Returns associated runtime sessions if any."""
        return self._job_service.runtime_sessions(self.job_id)

    def filtered_logs(self, **kwargs) -> str:
        """Returns logs of the job.
        Args:
            include: regex expression finds matching line in the log to be included
            exclude: regex expression finds matching line in the log to be excluded
        """
        return self._job_service.filtered_logs(job_id=self.job_id, **kwargs)

    def error_message(self):
        """Returns the execution error message."""
        if self.status() != "ERROR":
            return ""

        error_events = self.events(type="ERROR")
        if len(error_events) > 0:
            error_msg_list = [format_err_event(evt) for evt in error_events]
            return "\n\n".join(error_msg_list)

        error_result = self._job_service.result(self.job_id) if self.status() == "ERROR" else ""

        if isinstance(error_result, str):
            try:
                return error_result.strip('"').encode().decode("unicode_escape")
            except UnicodeDecodeError:
                logging.warning("Error decoding error message, returning raw message.")

        return error_result

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

        if self.status() == "ERROR":
            error_message = self.error_message()
            if error_message:
                raise QiskitServerlessException(error_message)

            raise QiskitServerlessException(self.filtered_logs(include=r"(?i)error|exception"))

        # Retrieve the results. If they're string format, try to decode to a dictionary.
        results = self._job_service.result(self.job_id)

        if isinstance(results, str):
            try:
                results = json.loads(results, cls=QiskitObjectsDecoder)
            except json.JSONDecodeError:
                logging.warning("Error during results decoding.")

        return results

    def events(self, **kwargs) -> list[JobEvent]:
        """Returns events of the job."""
        return self._job_service.events(self.job_id, **kwargs)

    def in_terminal_state(self) -> bool:
        """Checks if job is in terminal state"""
        return self.status() in _FINAL_STATUSES

    def wait_for_final_state(
        self, timeout: Optional[float] = None, poll_interval: Optional[float] = None, verbose: bool = False
    ) -> str:
        """Wait until the job is DONE, ERROR or CANCELED, and return that status.

        By default it checks after 1, 2, 4, 8, 16 and 32 s, then every 60 s, and starts again from 1 s when the
        main status changes or the job enters post-processing. A fixed ``poll_interval`` (at least 1 s) replaces
        that backoff. Short network errors and 429, 502, 503 or 504 answers are retried.

        Args:
            timeout: seconds to wait. ``None`` waits until the job ends. One status request can add up to its own
                request timeout on top.
            poll_interval: fixed seconds between checks instead of the backoff.
            verbose: print a header, one line per status change and per retried error, and the error message
                if the job ends in ERROR.

        Raises:
            TimeoutError: if the job does not end within ``timeout``. The job keeps running.
            QiskitServerlessException: on any other error, or when the retried errors last until ``timeout``, or
                for 5 minutes in a row when there is no timeout.

        Example:
            >>> job.wait_for_final_state(timeout=600, verbose=True)
            Waiting for job 3f2a1c0e-6b1d-4c0e-9a51-2f0c4d1e7a90
            0:00:00  QUEUED
            0:02:10  RUNNING
            0:41:44  DONE
            'DONE'
        """
        start = time.monotonic()
        deadline = None if timeout is None else start + timeout
        if verbose:
            print(f"Waiting for job {self.job_id}", flush=True)
        last_status = None
        failing_since = None
        step = 0
        while True:
            try:
                status = self.status()
                failing_since = None
            except QiskitServerlessException as error:
                if failing_since is None:
                    failing_since = time.monotonic()
                give_up = failing_since + _RETRY_SECONDS if deadline is None else deadline
                if not is_transient_error(error) or time.monotonic() >= give_up:
                    raise
                logger.info("Status check for job %s failed, retrying: %s", self.job_id, error)
                if verbose:
                    code = getattr(error, "_code", None)
                    print(f"{_elapsed(start)}  status check failed ({code}), retrying", flush=True)
                time.sleep(_next_wait(step, give_up, poll_interval))
                step += 1
                continue
            if status != last_status:
                if verbose:
                    print(f"{_elapsed(start)}  {status}", flush=True)
                if last_status is not None and _resets_backoff(last_status, status):
                    step = 0
                last_status = status
            if status in _FINAL_STATUSES:
                if verbose and status == "ERROR":
                    self._print_error_message()
                return status
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(f"Job {self.job_id} is still {status} after {timeout} s.")
            time.sleep(_next_wait(step, deadline, poll_interval))
            step += 1

    def _print_error_message(self):
        """Print why the job failed. A failure to fetch it does not change the result of the wait."""
        try:
            message = self.error_message()
        except Exception:  # pylint: disable=broad-exception-caught
            logger.info("Getting the error message for job %s failed.", self.job_id, exc_info=True)
            message = "Something went wrong getting the error message."
        if message:
            print(message, flush=True)

    def __repr__(self):
        return f"<Job | {self.job_id}>"


def send_error(code: Union[str, int], message: str, exception: str, args: Optional[Any] = None):
    """Send an error message to store it in the gateway.

    Args:
        code: The error code.
        message: A human readable text describing the error.
        args: Additional arguments to give further information. Should json format or empty.
    """

    version = os.environ.get(ENV_GATEWAY_PROVIDER_VERSION)
    if version is None:
        version = GATEWAY_PROVIDER_VERSION_DEFAULT

    token = os.environ.get(ENV_JOB_GATEWAY_TOKEN)
    if token is None:
        logging.warning(
            "The Error will be logged since there is no information about the "
            "authorization token in the environment."
        )
        logging.error("Error %s: %s\n%s", code, message, args)
        return False

    instance = os.environ.get(ENV_JOB_GATEWAY_INSTANCE, None)
    channel = os.environ.get(QISKIT_IBM_CHANNEL, None)
    url = f"{os.environ.get(ENV_JOB_GATEWAY_HOST)}/" f"api/{version}/jobs/{os.environ.get(ENV_JOB_ID_GATEWAY)}/event/"

    request_json: dict[str, Any] = {"type": "ERROR", "code": code, "message": message, "exception": exception}
    if args:
        request_json["args"] = args

    response = requests.post(
        url,
        json=request_json,
        headers=get_headers(token=token, instance=instance, channel=channel),
        timeout=REQUESTS_TIMEOUT,
    )

    if not response.ok:
        sanitized = response.text.replace("\n", "").replace("\r", "")
        logging.warning("Something went wrong sending error: %s", sanitized)
        logging.warning("The Error will be logged since there was an error sending the error.")
        logging.error("Error %s: %s\n%s", code, message, args)

    return response.ok


def _get_result_path() -> str:
    """Check if the file path specified by the ``RESULTS_PATH`` environment variable,
    which is set by the runner (Ray or Fleets) at job submission, exists and legal."""
    results_path = os.environ.get(RESULTS_PATH)
    if not results_path:
        raise QiskitServerlessException(
            "Error getting arguments: RESULTS_PATH environment variable is missing or empty"
        )

    os.makedirs(os.path.dirname(results_path), exist_ok=True)

    return results_path


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

    if not is_jsonable(result, cls=QiskitObjectsEncoder):
        logging.warning("Object passed is not json serializable.")
        return False

    result_path = _get_result_path()
    try:
        with open(result_path, "w", encoding="utf-8") as result_file:
            result_file.write(json.dumps(result or {}, cls=QiskitObjectsEncoder))

        logging.info("[save] job_id=%s | Result saved ok %s", ENV_JOB_ID_GATEWAY, result_path)
        return True
    except Exception as e:  # pylint: disable=broad-exception-caught
        logging.info("[save] job_id=%s | Error saving results %s: %ss", ENV_JOB_ID_GATEWAY, result_path, e)
        return False


def update_status(status: str):
    """Update sub status."""

    version = os.environ.get(ENV_GATEWAY_PROVIDER_VERSION)
    if version is None:
        version = GATEWAY_PROVIDER_VERSION_DEFAULT

    token = os.environ.get(ENV_JOB_GATEWAY_TOKEN)
    if token is None:
        logging.warning(
            "'sub_status' cannot be updated since "
            "there is no information about the "
            "authorization token in the environment."
        )
        return False

    instance = os.environ.get(ENV_JOB_GATEWAY_INSTANCE, None)
    channel = os.environ.get(QISKIT_IBM_CHANNEL, None)

    url = (
        f"{os.environ.get(ENV_JOB_GATEWAY_HOST)}/"
        f"api/{version}/jobs/{os.environ.get(ENV_JOB_ID_GATEWAY)}/sub_status/"
    )
    response = requests.patch(
        url,
        data={"sub_status": status},
        headers=get_headers(token=token, instance=instance, channel=channel),
        timeout=REQUESTS_TIMEOUT,
    )
    if not response.ok:
        sanitized = response.text.replace("\n", "").replace("\r", "")
        logging.warning("Something went wrong: %s", sanitized)

    return response.ok


STATUS_MAP = {
    Job.PENDING: "INITIALIZING",
    Job.RUNNING: "RUNNING",
    Job.STOPPING: "CANCELING",
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

INVERSE_STATUS_MAP = {value: key for key, value in STATUS_MAP.items()}


def _resets_backoff(previous: str, status: str) -> bool:
    """A new main status, or entering post-processing, resets the backoff. Other sub-statuses do not."""
    if status == STATUS_MAP[Job.POST_PROCESSING]:
        return True
    return _map_status_to_serverless(previous)[0] != _map_status_to_serverless(status)[0]


def _next_wait(step: int, deadline: Optional[float], poll_interval: Optional[float] = None) -> float:
    """Seconds to sleep before the next check, cut at the deadline."""
    if poll_interval is not None:
        wait = max(float(poll_interval), _MIN_POLL_INTERVAL_SECONDS)
    else:
        base = _BACKOFF_SECONDS[min(step, len(_BACKOFF_SECONDS) - 1)]
        wait = base * random.uniform(1 - _BACKOFF_JITTER, 1 + _BACKOFF_JITTER)
    if deadline is not None:
        wait = min(wait, max(deadline - time.monotonic(), 0))
    return wait


def _elapsed(start: float) -> str:
    """Time since start as H:MM:SS."""
    seconds = int(time.monotonic() - start)
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _map_status_from_serveless(status: str) -> str:
    """Map a status string from serverless terminology to the Qiskit terminology."""

    try:
        return STATUS_MAP[status]
    except KeyError:
        return status


def _map_status_to_serverless(status: str) -> Tuple[str, Union[str, None]]:
    """Map a status string from Qiskit terminology to the serverless terminology."""
    try:
        status_translation = INVERSE_STATUS_MAP[status]
    except KeyError:
        return status, None

    if status.startswith("RUNNING:"):
        return Job.RUNNING, status_translation
    return status_translation, None


def get_runtime_service(
    channel: Optional[str] = None,
    token: Optional[str] = None,
    instance: Optional[str] = None,
    url: Optional[str] = None,
) -> ServerlessRuntimeService:
    """Get a QiskitRuntimeService wrapped into a ServerlessRuntimeService instance
    that allows to associate runtime job ids to serverless job ids. All input arguments
    are optional, and the recommended usage within a QiskitFunction source code is
    ``get_runtime_service()``, which will automatically pull authentication data from the
    environment variables.

    Set ``QISKIT_IBM_PRIVATE_ENDPOINT`` to ``true`` to reach the Runtime API through a
    virtual private endpoint. It defaults to off, and the instance has to be a CRN for the
    private host to be resolved.

    Args:
        channel: Optional QiskitRuntimeService channel argument
        token: Optional QiskitRuntimeService authorization token
        instance: Optional QiskitRuntimeService instance (CRN or name)
        url: Optional QiskitRuntimeService url

    Returns:
        QiskitRuntimeService wrapped into a ServerlessRuntimeService instance that allows
        to associate serverless job ids to runtime job and sesison ids.
    """

    return ServerlessRuntimeService(
        channel=channel or os.environ["QISKIT_IBM_CHANNEL"],
        instance=instance or os.environ["QISKIT_IBM_INSTANCE"],
        token=token or os.environ["QISKIT_IBM_TOKEN"],
        url=url or os.environ.get("QISKIT_IBM_URL", None),
        private_endpoint=os.environ.get("QISKIT_IBM_PRIVATE_ENDPOINT", "false").lower() == "true",
    )


def is_running_in_serverless() -> bool:
    """Return ``True`` if running as a Qiskit serverless program, ``False`` otherwise."""
    return ENV_JOB_ID_GATEWAY in os.environ


def is_trial() -> bool:
    """Return ``True`` if Job is running in trial mode, ``False`` otherwise."""
    return os.getenv(ENV_ACCESS_TRIAL) == "True"
