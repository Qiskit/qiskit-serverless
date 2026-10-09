import json
import logging
import time
from uuid import UUID

from django.contrib.auth.models import AbstractUser
from qiskit_ibm_runtime import QiskitRuntimeService, RuntimeInvalidStateError

from core.models import Job, Program, RuntimeJob
from core.domain.exceptions.invalid_job_transition_exception import InvalidJobTransitionException
from core.services.job_transitions import JobTransitionService
from core.services.runners import get_runner, RunnerError
from api.access_policies.jobs import JobAccessPolicies
from api.domain.exceptions.engine_unavailable_exception import EngineUnavailableException
from api.domain.exceptions.job_not_found_exception import JobNotFoundException
from core.model_managers.job_events import JobEventContext, JobEventOrigin

logger = logging.getLogger("api.StopJobUseCase")

# One retry. The API has its own worker, so unlike the scheduler it can wait for a rate limit to
# clear, and gunicorn gives the whole request 25s. One runner serves both attempts, so the worst
# case is the IAM fetch once plus one cancel per attempt. test_stop.py pins the arithmetic.
_CANCEL_DELAYS = (1.0,)


class StopJobUseCase:
    """
    Use case for stopping a single job.
    """

    def __init__(self) -> None:
        self.status_messages = []
        self.stopped_sessions = []

    def execute(self, job_id: UUID, service_str: str, user: AbstractUser) -> str:
        job = Job.objects.filter(id=job_id).first()
        if job is None:
            raise JobNotFoundException(job_id)

        if not JobAccessPolicies.can_stop(user, job):
            raise JobNotFoundException(job_id)

        # reset stopped sessions and status messages
        self.status_messages = []
        self.stopped_sessions = []

        if job.status == Job.STOPPING:
            # No second cancel to send, but the runtime jobs may still be running: a stop the
            # scheduler started cancels the fleet and nothing else.
            self.status_messages.append("Job is already stopping.")
            self._cancel_runtime_jobs(job, service_str)
            return " ".join(self.status_messages)

        if job.in_terminal_state():
            self.status_messages.append("Job already in terminal state.")
            return " ".join(self.status_messages)

        try:
            # Kafka is disabled on the gateway, so the service sends nothing from here.
            transitions = JobTransitionService()
            if job.runner == Program.RAY:
                # Ray has no cancel to confirm. The cluster is asked to stop further down.
                transitions.to_stopped(job, origin=JobEventOrigin.API, context=JobEventContext.STOP_JOB)
            elif not self._try_stop_with_retries(transitions, job):
                transitions.to_stopped(job, origin=JobEventOrigin.API, context=JobEventContext.STOP_JOB)
        except RunnerError as ex:
            logger.warning("Could not cancel fleet_id=%s: %s", job.fleet_id, str(ex))
            raise EngineUnavailableException("Job could not be stopped right now, please retry.") from ex
        except InvalidJobTransitionException:
            # Lost the race. STOPPING is not terminal, so re-read before naming it.
            job.refresh_from_db(fields=["status"])
            if job.status not in (Job.STOPPING, Job.STOPPED):
                self.status_messages.append("Job already in terminal state.")
                return " ".join(self.status_messages)

        # A successful transition leaves the new status on the instance, so the row names itself.
        self.status_messages.append("Job is stopping." if job.status == Job.STOPPING else "Job has been stopped.")

        self._cancel_runtime_jobs(job, service_str)

        if job.runner == Program.RAY:
            self._stop_ray_job_if_active(job)

        return " ".join(self.status_messages)

    def _cancel_runtime_jobs(self, job: Job, service_str: str) -> None:
        """Cancel the Qiskit Runtime jobs this job started, if the caller sent a service."""
        # Unit tests send a None directly, but the client sends a serialized None
        service = None
        if service_str:
            service = json.loads(service_str, cls=json.JSONDecoder)
        runtime_jobs = RuntimeJob.objects.filter(job=job)

        if not service:
            self.status_messages.append("QiskitRuntimeService not found, cannot stop runtime jobs.")
        elif not runtime_jobs:
            self.status_messages.append("No active runtime job ID associated with this serverless job ID.")
        else:
            service_config = service["__value__"]
            qiskit_service = QiskitRuntimeService(**service_config)
            qiskit_api_client = qiskit_service._get_api_client()
            for runtime_job_entry in runtime_jobs:
                self._cancel_runtime_job_entry(runtime_job_entry, qiskit_service, qiskit_api_client)

    def _try_stop_with_retries(self, transitions: JobTransitionService, job: Job) -> bool:
        """Cancel the fleet, retrying once. Raises on the last attempt.

        Every failure is retried, not only the ones Code Engine did not answer: an expired IAM cache
        clears by itself, and a wrong API key is fixed outside this process. One runner for both
        attempts, so the IAM token is fetched once.
        """
        runner = get_runner(job) if job.fleet_id else None
        for delay in _CANCEL_DELAYS:
            try:
                return transitions.try_stop(
                    job, origin=JobEventOrigin.API, context=JobEventContext.STOP_JOB, runner=runner
                )
            except RunnerError as ex:
                logger.warning("Retrying cancel of fleet_id=%s in %.2fs: %s", job.fleet_id, delay, str(ex))
                time.sleep(delay)
        return transitions.try_stop(job, origin=JobEventOrigin.API, context=JobEventContext.STOP_JOB, runner=runner)

    def _cancel_runtime_job_entry(
        self,
        runtime_job_entry,
        qiskit_service,
        qiskit_api_client,
    ):
        job_id_str = runtime_job_entry.runtime_job
        session_id_str = runtime_job_entry.runtime_session
        job_instance = qiskit_service.job(job_id_str)

        if not job_instance:
            self.status_messages.append(
                f"Runtime job {job_id_str} not found in runtime service. "
                "Check that credentials used to authenticate match."
            )
            return

        if session_id_str:
            self._cancel_runtime_session(session_id_str, qiskit_api_client)
        else:
            self._cancel_runtime_job(job_instance, job_id_str)

    def _cancel_runtime_session(self, session_id, api_client):
        if session_id in self.stopped_sessions:
            return
        try:
            api_client.cancel_session(session_id)
            self.status_messages.append(f"Canceled runtime session: {session_id} and associated runtime jobs.")
            self.stopped_sessions.append(session_id)
        except Exception as e:
            self.status_messages.append(f"Runtime session {session_id} could not be canceled. Exception: {e}")

    def _cancel_runtime_job(self, job_instance, job_id_str):
        try:
            job_instance.cancel()
            self.status_messages.append(f"Canceled runtime job [{job_id_str}].")
        except RuntimeInvalidStateError:
            self.status_messages.append(f"Runtime job {job_id_str} could not be canceled (invalid state).")

    def _stop_ray_job_if_active(self, job: Job):
        runner = get_runner(job)
        if runner.is_active():
            try:
                stop_accepted = runner.stop()
                if stop_accepted:
                    self.status_messages.append("Serverless job stop has been requested.")
                else:
                    self.status_messages.append("Serverless job was already stopping or no longer running.")
            except RunnerError:
                logger.warning("job_id=%s Serverless job was not accessible from: %s", job.id, job.compute_resource)
                self.status_messages.append("Serverless job was not accessible.")
