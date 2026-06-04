"""
Use case for saving job results.
"""

from uuid import UUID
import logging
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ObjectDoesNotExist
from api.domain.exceptions.job_not_found_exception import JobNotFoundException
from api.access_policies.jobs import JobAccessPolicies
from core.services.storage import get_result_storage
from core.models import Job

logger = logging.getLogger("api.JobSaveResultUseCase")


class JobSaveResultUseCase:
    """
    Use case for saving the result of a Job.
    """

    def execute(self, job_id: UUID, user: AbstractUser, result: str) -> Job:
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
        try:
            job = Job.objects.select_related("program__code_engine_project").get(id=job_id)
        except ObjectDoesNotExist:
            raise JobNotFoundException(job_id)

        can_save_result = JobAccessPolicies.can_save_result(user, job)
        if not can_save_result:
            raise JobNotFoundException(job_id)

        result_storage = get_result_storage(job)
        result_storage.save(result)
        job.result = result

        return job
