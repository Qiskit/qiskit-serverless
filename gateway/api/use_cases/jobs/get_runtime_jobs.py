"""Use case: retrieve all RuntimeJob objects associated to a given Job."""

import logging
from uuid import UUID

from api.domain.exceptions.not_found_error import NotFoundError
from core.models import RuntimeJob
from api.repositories.jobs import JobsRepository
from api.repositories.runtime_job import RuntimeJobRepository

logger = logging.getLogger("gateway.use_cases.jobs")


class GetRuntimeJobsUseCase:
    """Retrieve all RuntimeJob objects associated to a given Job."""

    jobs_repository = JobsRepository()
    runtime_job_repository = RuntimeJobRepository()

    def execute(self, job_id: UUID) -> list[RuntimeJob]:
        """
        Return all RuntimeJob objects associated to a given Job.

        Args:
            job_id: Target Job ID.

        Returns:
            The list of RuntimeJobs.

        Raises:
            NotFoundError: If the job does not exist or access is denied.
        """
        job = self.jobs_repository.get_job_by_id(job_id)

        if job is None:
            raise NotFoundError(f"Job [{job_id}] not found")

        return self.runtime_job_repository.get_runtime_job(job)
