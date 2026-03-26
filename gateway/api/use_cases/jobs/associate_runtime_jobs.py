"""Use case: associate a RuntimeJob object to a given Job."""

import logging
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist

from api.domain.exceptions.job_not_found_exception import JobNotFoundException
from api.repositories.runtime_job import RuntimeJobRepository
from core.models import Job

logger = logging.getLogger("gateway.use_cases.jobs")


class AssociateRuntimeJobsUseCase:
    """Associate a RuntimeJob object to a given Job."""

    runtime_job_repository = RuntimeJobRepository()

    def execute(self, job_id: UUID, runtime_job: str, runtime_session: str | None) -> str:
        """
        Associate a RuntimeJob object to a given Job.

        Args:
            job_id: Target Job ID.
            runtime_job: Runtime job ID to associate.
            runtime_session: Optional runtime session ID to associate.

        Returns:
            The updated Job.

        Raises:
            NotFoundError: If the job does not exist or access is denied.
        """
        try:
            job = Job.objects.get(id=job_id)
        except ObjectDoesNotExist:
            raise JobNotFoundException(job_id)

        try:
            self.runtime_job_repository.create_runtime_job(job, runtime_job, runtime_session)
            message = f"RuntimeJob object [{runtime_job}] created " f"for serverless job id [{job_id}]."
        except Exception as e:
            message = f"Failed to create RuntimeJob object " f"[{runtime_job}] for job id [{job_id}]. Error: {e}"
            logger.error(message)

        return message
