"""Use case: associate a RuntimeJob object to a given Job."""

import logging
from uuid import UUID

from api.domain.exceptions.not_found_error import NotFoundError
from api.models import RuntimeJob
from api.repositories.jobs import JobsRepository

logger = logging.getLogger("gateway.use_cases.jobs")


class AssociateRuntimeJobsUseCase:
    """Associate a RuntimeJob object to a given Job."""

    jobs_repository = JobsRepository()

    def execute(
        self, job_id: UUID, runtime_job: str, runtime_session: str | None
    ) -> str:
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
        job = self.jobs_repository.get_job_by_id(job_id)
        if job is None:
            raise NotFoundError(f"Job [{job_id}] not found")

        try:
            RuntimeJob.objects.create(
                job=job,
                runtime_job=runtime_job,
                runtime_session=runtime_session,
            )
            message = (
                f"RuntimeJob object [{runtime_job}] created "
                f"for serverless job id [{job_id}]."
            )
        except Exception as e:
            message = (
                f"Failed to create RuntimeJob object "
                f"[{runtime_job}] for job id [{job_id}]. Error: {e}"
            )

        return message
