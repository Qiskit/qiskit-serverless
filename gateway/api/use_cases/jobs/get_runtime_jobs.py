"""Use case: retrieve all RuntimeJob objects associated to a given Job."""

import logging
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist

from api.access_policies.jobs import JobAccessPolicies
from api.domain.exceptions.job_not_found_exception import JobNotFoundException
from api.repositories.runtime_job import RuntimeJobRepository
from core.models import Job, RuntimeJob

logger = logging.getLogger("api.GetRuntimeJobsUseCase")


class GetRuntimeJobsUseCase:
    """Retrieve all RuntimeJob objects associated to a given Job."""

    runtime_job_repository = RuntimeJobRepository()

    def execute(self, job_id: UUID, user) -> list[RuntimeJob]:
        """
        Return all RuntimeJob objects associated to a given Job.

        Args:
            job_id: Target Job ID.
            user: Requesting user (must be the job author).

        Returns:
            The list of RuntimeJobs.

        Raises:
            NotFoundError: If the job does not exist or access is denied.
        """
        try:
            job = Job.objects.get(id=job_id)
        except ObjectDoesNotExist:
            raise JobNotFoundException(job_id)

        if not JobAccessPolicies.can_manage_runtime_jobs(user, job):
            raise JobNotFoundException(job_id)

        return self.runtime_job_repository.get_runtime_job(job)
