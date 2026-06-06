"""Use case for retrieving job results via presigned URL or inline content."""

import logging
from uuid import UUID

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ObjectDoesNotExist

from api.access_policies.jobs import JobAccessPolicies
from api.domain.exceptions.job_not_found_exception import JobNotFoundException
from api.use_cases.jobs.result_fetch_result import ResultFetchResult
from core.models import Job, Program
from core.services.storage import get_result_storage

logger = logging.getLogger("api.GetJobResultUseCase")


class GetJobResultUseCase:
    """Retrieve the result of a job, returning a redirect URL or inline content."""

    def execute(self, job_id: UUID, user: AbstractUser) -> ResultFetchResult:
        """Return the result of a job if the user has access.

        Returns:
            ResultFetchResult with redirect_url set (Fleet, result ready),
            ResultFetchResult() with both fields None (no result yet),
            or ResultFetchResult with raw_result set (Ray).
        """
        try:
            job = Job.objects.get(id=job_id)
        except ObjectDoesNotExist:
            raise JobNotFoundException(str(job_id))

        if not JobAccessPolicies.can_read_result(user, job):
            raise JobNotFoundException(str(job_id))

        result_storage = get_result_storage(job)

        if job.program.runner == Program.FLEETS:
            url = result_storage.get_url()
            if url:
                logger.info(
                    "[jobs-result] user_id=%s job_id=%s | Redirecting to presigned URL",
                    user.id,
                    job_id,
                )
                return ResultFetchResult(redirect_url=url)
            return ResultFetchResult()

        # Ray path
        raw = result_storage.get()
        if raw:
            return ResultFetchResult(raw_result=raw)
        return ResultFetchResult()
