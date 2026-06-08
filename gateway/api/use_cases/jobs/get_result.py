"""Use case: retrieve job result."""

import logging
from typing import cast
from uuid import UUID

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ObjectDoesNotExist

from api.access_policies.jobs import JobAccessPolicies
from api.domain.exceptions.job_not_found_exception import JobNotFoundException
from api.use_cases.jobs.get_result_response import GetResultResponse
from core.models import Job, Program
from core.services.storage import get_result_storage
from core.services.storage.result_storage_fleets import FleetsResultStorage

logger = logging.getLogger("api.GetJobResultUseCase")


class GetJobResultUseCase:
    """Use case for retrieving job results."""

    def execute(self, job_id: UUID, user: AbstractUser) -> GetResultResponse:
        """Return the result of a job if the user has access.

        Returns:
            GetResultResponse with redirect_url set (Fleet, result ready),
            GetResultResponse(result_ready=False) (Fleet, no result yet),
            or GetResultResponse with raw_result set (Ray).
        """
        try:
            job = Job.objects.get(id=job_id)
        except ObjectDoesNotExist:
            raise JobNotFoundException(job_id)

        if not JobAccessPolicies.can_read_result(user, job):
            raise JobNotFoundException(job_id)

        storage = get_result_storage(job)

        if job.program.runner == Program.FLEETS:
            try:
                url = cast(FleetsResultStorage, storage).get_url()
            except (ValueError, NotImplementedError):
                url = None
            if url:
                logger.info("[jobs-result] user_id=%s job_id=%s | Redirecting to presigned URL", user.id, job_id)
                return GetResultResponse(redirect_url=url)
            return GetResultResponse()

        raw = storage.get()
        logger.info("[jobs-result] user_id=%s job_id=%s | Result retrieved ok", user.id, job_id)
        return GetResultResponse(raw_result=raw)
