import json
import logging
from uuid import UUID

from qiskit_ibm_runtime import QiskitRuntimeService, RuntimeInvalidStateError

from api.models import Job
from api.ray import get_job_handler
from api.repositories.jobs import JobsRepository
from api.domain.exceptions.not_found_error import NotFoundError
from api.repositories.runtime_job import RuntimeJobRepository


logger = logging.getLogger("gateway.use_cases.jobs")


class StopJobUseCase:
    """
    Use case for stopping a single job.
    """

    jobs_repository = JobsRepository()
    runtime_jobs_repository = RuntimeJobRepository()

    def execute(self, job_id: UUID, service_str: str) -> str:
        job = self.jobs_repository.get_job_by_id(job_id)
        if job is None:
            raise NotFoundError(f"Job [{job_id}] not found")

        status_messages = []

        if not job.in_terminal_state():
            job.status = Job.STOPPED
            job.save(update_fields=["status"])
            status_messages.append("Job has been stopped.")
        else:
            status_messages.append("Job already in terminal state.")

        service = json.loads(service_str, cls=json.JSONDecoder) if service_str else None
        runtime_jobs = self.runtime_jobs_repository.get_runtime_job(job)

        if not service:
            status_messages.append(
                "QiskitRuntimeService not found, cannot stop runtime jobs."
            )
        elif not runtime_jobs:
            status_messages.append(
                "No active runtime job ID associated with this serverless job ID."
            )
        else:
            service_config = service["__value__"]
            qiskit_service = QiskitRuntimeService(**service_config)
            qiskit_api_client = qiskit_service._get_api_client()

            stopped_sessions = []
            for runtime_job_entry in runtime_jobs:
                self._cancel_runtime_job_entry(
                    runtime_job_entry,
                    qiskit_service,
                    qiskit_api_client,
                    status_messages,
                    stopped_sessions,
                )

        self._stop_ray_job_if_active(job, status_messages)

        return " ".join(status_messages)

    @staticmethod
    def _cancel_runtime_job_entry(
        runtime_job_entry,
        qiskit_service,
        qiskit_api_client,
        status_messages,
        stopped_sessions,
    ):
        job_id_str = runtime_job_entry.runtime_job
        session_id_str = runtime_job_entry.runtime_session
        job_instance = qiskit_service.job(job_id_str)

        if not job_instance:
            status_messages.append(
                f"Runtime job {job_id_str} not found in runtime service. "
                "Check that credentials used to authenticate match."
            )
            return

        if session_id_str:
            StopJobUseCase._cancel_runtime_session(
                session_id_str, qiskit_api_client, status_messages, stopped_sessions
            )
        else:
            StopJobUseCase._cancel_runtime_job(
                job_instance, job_id_str, status_messages
            )

    @staticmethod
    def _cancel_runtime_session(
        session_id, api_client, status_messages, stopped_sessions
    ):
        if session_id in stopped_sessions:
            return
        try:
            api_client.cancel_session(session_id)
            status_messages.append(
                f"Canceled runtime session: {session_id} and associated runtime jobs."
            )
            stopped_sessions.append(session_id)
        except Exception as e:
            status_messages.append(
                f"Runtime session {session_id} could not be canceled. Exception: {e}"
            )

    @staticmethod
    def _cancel_runtime_job(job_instance, job_id_str, status_messages):
        try:
            job_instance.cancel()
            status_messages.append(f"Canceled runtime job [{job_id_str}].")
        except RuntimeInvalidStateError:
            status_messages.append(
                f"Runtime job {job_id_str} could not be canceled (invalid state)."
            )

    @staticmethod
    def _stop_ray_job_if_active(job, status_messages):
        if job.compute_resource and job.compute_resource.active:
            job_handler = get_job_handler(job.compute_resource.host)
            if job_handler is not None:
                was_running = job_handler.stop(job.ray_job_id)
                if was_running:
                    status_messages.append("Ray job was running and has been stopped.")
                else:
                    status_messages.append("Ray job was already not running.")
            else:
                logger.warning(
                    "Ray compute resource is not accessible %s", job.compute_resource
                )
                status_messages.append("Ray compute resource not accessible.")
