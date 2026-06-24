"""Use case: associate a RuntimeJob object to a given Job."""

import logging
from uuid import UUID

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ObjectDoesNotExist

from api.access_policies.jobs import JobAccessPolicies
from api.domain.exceptions.job_not_found_exception import JobNotFoundException
from core.models import Job, RuntimeJob

logger = logging.getLogger("api.AssociateRuntimeJobsUseCase")


class AssociateRuntimeJobsUseCase:
    """Associate a RuntimeJob object to a given Job."""

    def execute(self, job_id: UUID, runtime_job: str, runtime_session: str | None, user: AbstractUser) -> str:
        """
        Associate a RuntimeJob object to a given Job.

        Args:
            job_id: Target Job ID.
            runtime_job: Runtime job ID to associate.
            runtime_session: Optional runtime session ID to associate.
            user: Requesting user (must be the job author).

        Returns:
            The updated Job.

        Raises:
            NotFoundError: If the job does not exist or access is denied.
        """
        try:
            job = Job.objects.get(id=job_id)
        except ObjectDoesNotExist:
            raise JobNotFoundException(job_id)

        if not JobAccessPolicies.can_manage_runtime_jobs(user, job):
            raise JobNotFoundException(job_id)

        try:
            RuntimeJob.objects.create(job=job, runtime_job=runtime_job, runtime_session=runtime_session)
            message = f"RuntimeJob object [{runtime_job}] created " f"for serverless job id [{job_id}]."
        except Exception as e:
            message = f"Failed to create RuntimeJob object " f"[{runtime_job}] for job id [{job_id}]. Error: {e}"
            logger.error(message)

        return message
