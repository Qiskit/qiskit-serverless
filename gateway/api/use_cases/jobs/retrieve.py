"""This module contains the usecase get_job"""

import logging
from uuid import UUID
from django.contrib.auth.models import AbstractUser
from api.domain.exceptions.not_found_error import NotFoundError
from core.models import Job
from api.repositories.jobs import JobsRepository
from api.access_policies.jobs import JobAccessPolicies
from core.services.storage.result_storage import ResultStorage

logger = logging.getLogger("gateway.use_cases.jobs")


class JobRetrieveUseCase:
    """Use case for retrieving a single job."""

    jobs_repository = JobsRepository()

    def execute(self, job_id: UUID, user: AbstractUser, with_result: bool) -> Job:
        """
        Retrieve job.

        Args:
            job_id: id of the job to retrieve
            user: author of the job
            with_result: retrieve the job with out without the job result

        Returns:
            Job: job found
        """
        job = self.jobs_repository.get_job_by_id(job_id)
        if job is None:
            raise NotFoundError(f"Job [{job_id}] not found")

        if not JobAccessPolicies.can_access(user, job):
            raise NotFoundError(f"Job [{job_id}] not found")

        can_read_result = JobAccessPolicies.can_read_result(user, job)

        if with_result and can_read_result:
            result_store = ResultStorage(job.author.username)
            result = result_store.get(str(job.id))
            if result is not None:
                job.result = result
        else:
            job.result = None

        return job
