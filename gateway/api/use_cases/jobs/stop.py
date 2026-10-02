import json
import logging
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
            # The scheduler owns the rest of it. Cancelling again would write a second STOPPING event,
            # which is what the deadline is measured from, and writing STOPPED here would end the job
            # before Code Engine confirmed it.
            self.status_messages.append("Job is already stopping.")
            return " ".join(self.status_messages)

        # STOPPING means Code Engine accepted the cancel, so the cancel goes out before the status is
        # written. The scheduler only confirms it from the task store afterwards. The status read here
        # may be stale, so it only avoids a pointless call; the transition below is the real check.
        is_fleets = job.runner == Program.FLEETS
        cancel_in_flight = self._cancel_fleet(job) if is_fleets and job.status not in Job.TERMINAL_STATUSES else False

        stopped = False
        try:
            # Lock transaction to read the fresh status. It could raise InvalidJobTransitionException if the job
            # was SUCCEEDED or FAILED
            # Only the scheduler sends Kafka messages: the gateway has Kafka disabled, so the service sends nothing here
            transitions = JobTransitionService()
            if cancel_in_flight:
                transitions.to_stopping(job, origin=JobEventOrigin.API, context=JobEventContext.STOP_JOB)
            else:
                transitions.to_stopped(job, origin=JobEventOrigin.API, context=JobEventContext.STOP_JOB)
            stopped = True
        except InvalidJobTransitionException:
            # Lost the race. Re-read so the message names the status the row is actually in.
            job.refresh_from_db(fields=["status"])

        if stopped:
            # New behavior: now, stopping a completed job (failed or succeeded) NO longer (attempts to) stop its
            # runtime jobs.
            self.status_messages.append("Job is stopping." if cancel_in_flight else "Job has been stopped.")

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

            if not is_fleets:
                self._stop_ray_job_if_active(job)
        elif job.status == Job.STOPPING:
            # Reached when another worker won the race and moved the row to STOPPING between the
            # read above and the locked transition. The sequential case returns earlier.
            self.status_messages.append("Job is already stopping.")
        else:
            self.status_messages.append("Job already in terminal state.")

        return " ".join(self.status_messages)

    def _cancel_fleet(self, job: Job) -> bool:
        """Ask Code Engine to cancel the fleet. True when a cancel is in flight, so STOPPING is owed.

        A job with no fleet, and a fleet Code Engine says is gone, have nothing to wait for and go
        straight to STOPPED.
        """
        if not job.fleet_id:
            return False
        try:
            return get_runner(job).stop()
        except RunnerError as ex:
            logger.warning("Could not cancel fleet_id=%s: %s", job.fleet_id, str(ex))
            if ex.permanent:
                # Retrying cannot clear it, so report the stop rather than ask the user to try for ever.
                return False
            raise EngineUnavailableException("Job could not be stopped right now, please retry.") from ex

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
                if job.compute_resource:
                    logger.warning("Serverless job was not accessible from: %s", job.compute_resource)
                else:
                    logger.warning("Serverless job was not accessible: fleet_id=%s", job.fleet_id)
                self.status_messages.append("Serverless job was not accessible.")
