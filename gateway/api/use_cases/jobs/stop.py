import json
import logging
from uuid import UUID

from qiskit_ibm_runtime import QiskitRuntimeService, RuntimeInvalidStateError

from api.models import Job, JobEvents
from core.services.ray import get_job_handler
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

    def __init__(self) -> None:
        self.status_messages = []
        self.stopped_sessions = []

    def execute(self, job_id: UUID, service_str: str) -> str:
        job = self.jobs_repository.get_job_by_id(job_id)
        if job is None:
            raise NotFoundError(f"Job [{job_id}] not found")

        # reset stopped sessions and status messages
        self.status_messages = []
        self.stopped_sessions = []

        if not job.in_terminal_state():
            job.status = Job.STOPPED
            job.save(update_fields=["status"])
            JobEvents.objects.add_status_event(
                job_id=job.id, context="API - StopJob", status=job.status
            )
            self.status_messages.append("Job has been stopped.")
        else:
            self.status_messages.append("Job already in terminal state.")

        # Unit tests send a None directly, but the client sends a serialized None
        service = None
        if service_str:
            service = json.loads(service_str, cls=json.JSONDecoder)
        runtime_jobs = self.runtime_jobs_repository.get_runtime_job(job)

        if not service:
            self.status_messages.append(
                "QiskitRuntimeService not found, cannot stop runtime jobs."
            )
        elif not runtime_jobs:
            self.status_messages.append(
                "No active runtime job ID associated with this serverless job ID."
            )
        else:
            service_config = service["__value__"]
            qiskit_service = QiskitRuntimeService(**service_config)
            qiskit_api_client = qiskit_service._get_api_client()
            for runtime_job_entry in runtime_jobs:
                self._cancel_runtime_job_entry(
                    runtime_job_entry, qiskit_service, qiskit_api_client
                )

        self._stop_ray_job_if_active(job)

        return " ".join(self.status_messages)

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
            self.status_messages.append(
                f"Canceled runtime session: {session_id} and associated runtime jobs."
            )
            self.stopped_sessions.append(session_id)
        except Exception as e:
            self.status_messages.append(
                f"Runtime session {session_id} could not be canceled. Exception: {e}"
            )

    def _cancel_runtime_job(self, job_instance, job_id_str):
        try:
            job_instance.cancel()
            self.status_messages.append(f"Canceled runtime job [{job_id_str}].")
        except RuntimeInvalidStateError:
            self.status_messages.append(
                f"Runtime job {job_id_str} could not be canceled (invalid state)."
            )

    def _stop_ray_job_if_active(self, job):
        if job.compute_resource and job.compute_resource.active:
            job_handler = get_job_handler(job.compute_resource.host)
            if job_handler is not None:
                was_running = job_handler.stop(job.ray_job_id)
                if was_running:
                    self.status_messages.append(
                        "Serverless job was running and has been stopped."
                    )
                else:
                    self.status_messages.append(
                        "Serverless job was already not running."
                    )
            else:
                logger.warning(
                    "Serverless job was not accessible from: %s", job.compute_resource
                )
                self.status_messages.append("Serverless job was not accessible.")
