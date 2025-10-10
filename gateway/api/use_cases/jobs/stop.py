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
        """
        Stop job.

        Args:
            job_id: id of the job to stop
            service: service of the job
        """
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

        # Unit tests send a None directly, but the client sends a serialized None
        if service_str:
            service = json.loads(service_str, cls=json.JSONDecoder)
        else:
            service = None
        runtime_jobs = self.runtime_jobs_repository.get_runtime_job(job)
        if not service:
            status_messages.append(
                f"QiskitRuntimeService not found, cannot stop runtime jobs."
            )
        elif not runtime_jobs:
            status_messages.append(
                f"No active runtime job ID associated with this job ID."
            )

        if runtime_jobs and service:
            service_config = service["__value__"]
            qiskit_service = QiskitRuntimeService(**service_config)

            stopped_sessions = []
            for runtime_job_entry in runtime_jobs:
                job_id_str = runtime_job_entry.runtime_job
                session_id_str = runtime_job_entry.runtime_session
                job_instance = qiskit_service.job(job_id_str)

                if job_instance:
                    if session_id_str:
                        if session_id_str in stopped_sessions:
                            continue
                        try:
                            qiskit_service._get_api_client().cancel_session(
                                session_id_str
                            )
                            status_messages.append(
                                f"Canceled runtime session: {session_id_str} and associated runtime jobs."
                            )
                            stopped_sessions.append(session_id_str)
                        except Exception as e:
                            status_messages.append(
                                f"Runtime session {session_id_str} could not be canceled. Exception: {e}"
                            )
                    else:
                        try:
                            job_instance.cancel()
                            status_messages.append(
                                f"Canceled runtime job [{job_id_str}]."
                            )
                        except RuntimeInvalidStateError:
                            status_messages.append(
                                f"Runtime job {job_id_str} could not be canceled (invalid state)."
                            )
                else:
                    status_messages.append(
                        f"Runtime job {job_id_str} not found in runtime service. "
                        "Check that credentials used to authenticate match."
                    )

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

        return " ".join(status_messages)
