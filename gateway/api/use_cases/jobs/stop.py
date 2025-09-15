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

    def execute(self, job_id: UUID, service: str) -> str:
        """
        Stop job.

        Args:
            job_id: id of the job to stop
            service: service of the job
        """
        job = self.jobs_repository.get_job_by_id(job_id)
        if job is None:
            raise NotFoundError(f"Job [{job_id}] not found")

        message = "Job has been stopped."

        if not job.in_terminal_state():
            job.status = Job.STOPPED
            job.save(update_fields=["status"])

        runtime_jobs = self.runtime_jobs_repository.get_runtime_job(job)

        if runtime_jobs and service:
            service_config = json.loads(service, cls=json.JSONDecoder)["__value__"]
            qiskit_service = QiskitRuntimeService(**service_config)

            for runtime_job_entry in runtime_jobs:
                job_instance = qiskit_service.job(runtime_job_entry.runtime_job)
                if job_instance:
                    try:
                        logger.info("canceling [%s]", runtime_job_entry.runtime_job)
                        job_instance.cancel()
                    except RuntimeInvalidStateError:
                        logger.warning("cancel failed")

                    if job_instance.session_id:
                        qiskit_service._get_api_client().cancel_session(
                            job_instance.session_id
                        )  # pylint: disable=protected-access

        if job.compute_resource and job.compute_resource.active:
            job_handler = get_job_handler(job.compute_resource.host)
            if job_handler is not None:
                was_running = job_handler.stop(job.ray_job_id)
                if not was_running:
                    message = "Job was already not running."
            else:
                logger.warning(
                    "Compute resource is not accessible %s", job.compute_resource
                )

        return message
