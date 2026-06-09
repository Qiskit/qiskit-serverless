"""This module contains the usecase get_job"""

import logging
from typing import Optional
from uuid import UUID
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ObjectDoesNotExist
from api.domain.exceptions.job_not_found_exception import JobNotFoundException
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Job
from api.access_policies.jobs import JobAccessPolicies
from core.services.storage import get_result_storage

logger = logging.getLogger("api.JobRetrieveUseCase")


class JobRetrieveUseCase:
    """Use case for retrieving a single job."""

    def execute(
        self,
        job_id: UUID,
        user: AbstractUser,
        with_result: bool,
        accessible_functions: Optional[FunctionAccessResult] = None,
    ) -> Job:
        """
        Retrieve job.

        Args:
            job_id: id of the job to retrieve
            user: author of the job
            with_result: retrieve the job with out without the job result
            accessible_functions: result from FunctionAccessClient; if None or
                use_legacy_authorization=True, falls back to Django groups

        Returns:
            Job: job found
        """
        job = Job.objects.get(id=job_id)
        if job is None:
            raise JobNotFoundException(str(job_id))

        if not JobAccessPolicies.can_access(user, job, accessible_functions=accessible_functions):
            raise JobNotFoundException(str(job_id))

        if with_result:
            job.result = self.get_result(user, job)

        return job

    @staticmethod
    def get_result(user, job) -> str | None:
        if JobAccessPolicies.can_read_result(user, job):
            try:
                result_store = get_result_storage(job)
                return result_store.get()
            except (ValueError, NotImplementedError) as e:
                logger.warning("[jobs-retrieve] job_id=%s | Result unavailable: %s", str(job.id), e)
        return None
