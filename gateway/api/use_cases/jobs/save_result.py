"""
Use case for saving job results.
"""
from uuid import UUID
import logging
import json
from django.contrib.auth.models import AbstractUser
from api.repositories.jobs import JobsRepository
from api.domain.exceptions.not_found_error import NotFoundError
from api.access_policies.jobs import JobAccessPolicies
from api.services.storage.result_storage import ResultStorage
from api.models import Job

logger = logging.getLogger("gateway.use_cases.jobs")


class JobSaveResultUseCase:
    """
    Use case for saving the result of a Job.
    """

    jobs_repository = JobsRepository()

    def execute(self, job_id: UUID, user: AbstractUser, result: dict) -> Job:
        """Save a result for a given job.

        Args:
            job_id (str): Unique identifier of the job.
            user (AbstractUser): The user attempting to save the result.
            result (dict): The result data to be saved.

        Raises:
            NotFoundError: If the job does not exist or the user is not allowed to save results.

        Returns:
            Job: The updated job object with the stored result.
        """
        job = self.jobs_repository.get_job_by_id(job_id)
        if job is None:
            raise NotFoundError(f"Job [{job_id}] not found")

        can_save_result = JobAccessPolicies.can_save_result(user, job)
        if not can_save_result:
            raise NotFoundError(f"Job [{job_id}] not found")

        job.result = json.dumps(result)
        result_storage = ResultStorage(user.username)
        result_storage.save(job.id, job.result)

        return job
